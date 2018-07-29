from flask import render_template, redirect, url_for, flash

from flask_login import current_user

from wtforms import SubmitField, BooleanField, FormField, FieldList
from wtforms.validators import Required

from main import db
from models.volunteer.role import Role
from models.volunteer.volunteer import Volunteer as VolunteerUser

from . import volunteer
from ..common.forms import Form, HiddenIntegerField


class RoleSelectForm(Form):
    role_id = HiddenIntegerField('Role ID', [Required()])
    signup = BooleanField('Role')

class RoleSignupForm(Form):
    roles = FieldList(FormField(RoleSelectForm))
    submit = SubmitField('Sign up for these roles.')

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
# @volunteer.v_user_required()
@volunteer.route('/choose-roles', methods=['GET', 'POST'])
def choose_role():
    form = RoleSignupForm()

    form.add_roles(Role.get_all())
    current_volunteer = VolunteerUser.get_for_user(current_user)

    if form.validate_on_submit():
        current_role_ids = [r.id for r in current_volunteer.roles]

        for r in form.roles:
            r_id = r._role.id
            if r.signup.data and r_id not in current_role_ids:
                current_volunteer.roles.append(r._role)

            elif not r.signup.data and r_id in current_role_ids:
                current_volunteer.roles.remove(r._role)

        db.session.commit()
        flash("Updated your preferred roles")
        return redirect(url_for('.choose_role'))

    current_roles = current_volunteer.roles.all()
    if current_roles:
        role_ids = [r.id for r in current_roles]
        form.select_roles(role_ids)


    return render_template('volunteer/choose_role.html', form=form)
