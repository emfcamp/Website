import markdown
from os import path

from flask import (
    render_template, redirect, url_for, flash, Markup, request
)
from flask_login import current_user

from wtforms import SubmitField, BooleanField, FormField, FieldList
from wtforms.validators import InputRequired

from main import db
from models.volunteer.role import Role
from models.volunteer.volunteer import Volunteer as VolunteerUser

from . import volunteer, v_user_required, role_name_to_markdown_file
from ..common import feature_flag
from ..common.forms import Form, HiddenIntegerField


class RoleSelectForm(Form):
    role_id = HiddenIntegerField('Role ID', [InputRequired()])
    signup = BooleanField('Role')

class RoleSignupForm(Form):
    roles = FieldList(FormField(RoleSelectForm))
    submit = SubmitField('Sign up for these roles')

    def add_roles(self, roles):
        # Don't add roles if some have already been set (this will get called
        # on POST as well as GET)
        if len(self.roles) == 0:
            for r in roles:
                self.roles.append_entry()
                self.roles[-1].role_id.data = r.id

        role_dict = {r.id: r for r in roles}
        # Enrich the field data
        for field in self.roles:
            field._role = role_dict[field.role_id.data]
            field.label = field._role.name

    def select_roles(self, role_ids):
        for r in self.roles:
            if r._role.id in role_ids:
                r.signup.data = True

# TODO need to actually implement permissions
@volunteer.route('/choose-roles', methods=['GET', 'POST'])
@feature_flag('VOLUNTEERS_SIGNUP')
@v_user_required
def choose_role():
    form = RoleSignupForm()

    current_volunteer = VolunteerUser.get_for_user(current_user)
    if not current_volunteer.over_18:
        roles = Role.query.filter_by(over_18_only=False)
    else:
        roles = Role.query

    form.add_roles(roles.order_by(Role.name).all())

    if form.validate_on_submit():
        current_role_ids = [r.id for r in current_volunteer.interested_roles]

        for r in form.roles:
            r_id = r._role.id
            if r.signup.data and r_id not in current_role_ids:
                current_volunteer.interested_roles.append(r._role)

            elif not r.signup.data and r_id in current_role_ids:
                current_volunteer.interested_roles.remove(r._role)

        db.session.commit()
        flash("Your role list has been updated", 'info')
        return redirect(url_for('.choose_role'))

    current_roles = current_volunteer.interested_roles.all()
    if current_roles:
        role_ids = [r.id for r in current_roles]
        form.select_roles(role_ids)

    return render_template('volunteer/choose_role.html', form=form)


@volunteer.route('/role/<role_id>', methods=["GET", "POST"])
@feature_flag('VOLUNTEERS_SIGNUP')
@v_user_required
def role(role_id):
    role = Role.query.get_or_404(role_id)
    current_volunteer = VolunteerUser.get_for_user(current_user)

    if request.method == "POST":
        if role_id in current_volunteer.interested_roles:
            current_volunteer.interested_roles.remove(role)
        else:
            current_volunteer.interested_roles.append(role)
        db.session.commit()
        flash("Your role list has been updated", "info")
        return redirect(url_for('.choose_role'))

    role_description_file = role_name_to_markdown_file(role.name)

    if path.exists(role_description_file):
        content = open(role_description_file, 'r').read()
        description = Markup(markdown.markdown(content, extensions=["markdown.extensions.nl2br"]))
    else:
        description = None

    return render_template('volunteer/role.html', description=description,
                           role=role, current_volunteer=current_volunteer)

