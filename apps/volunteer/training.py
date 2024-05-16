# coding=utf-8

from flask import render_template, flash, current_app as app, redirect, url_for

from wtforms import SubmitField, BooleanField, FormField, FieldList
from wtforms.validators import InputRequired

from apps.volunteer.choose_roles import role_admin_required
from main import db

from models.volunteer.role import Role
from models.volunteer.volunteer import Volunteer

from . import volunteer
from ..common.forms import Form
from ..common.fields import HiddenIntegerField


class VolunteerSelectForm(Form):
    volunteer_id = HiddenIntegerField("Volunteer ID", [InputRequired()])
    trained = BooleanField("Volunteer")


class TrainingForm(Form):
    volunteers = FieldList(FormField(VolunteerSelectForm))
    submit = SubmitField("Train these volunteers.")

    def add_volunteers(self, volunteers):
        # Don't add roles if some have already been set (this will get called
        # on POST as well as GET)
        if len(self.volunteers) == 0:
            for v in volunteers:
                self.volunteers.append_entry()
                self.volunteers[-1].volunteer_id.data = v.id

        volunteer_dict = {v.id: v for v in volunteers}
        # Enrich the field data
        for field in self.volunteers:
            field._volunteer = volunteer_dict[field.volunteer_id.data]
            field.label = field._volunteer.nickname


@volunteer.route("/role-admin/<role_id>/train-users", methods=["GET", "POST"])
@role_admin_required
def train_users(role_id):
    role = Role.get_by_id(role_id)
    form = TrainingForm()
    volunteers = Volunteer.query.join(Volunteer.interested_roles).filter(Role.id == role_id).all()
    form.add_volunteers(volunteers)

    if form.validate_on_submit():
        changes = 0
        for v in form.volunteers:
            if v.trained.data and v._volunteer not in role.trained_volunteers:
                changes += 1
                role.trained_volunteers.append(v._volunteer)

            elif not v.trained.data and v._volunteer in role.trained_volunteers:
                changes += 1
                role.trained_volunteers.remove(v._volunteer)

        db.session.commit()
        flash("Trained %d volunteers" % changes)
        app.logger.info("Trained %d volunteers" % changes)

        return redirect(url_for(".train_users", role_id=role_id))

    for v in role.trained_volunteers:
        for f in form.volunteers:
            if f.volunteer_id.data == v.id:
                f.trained.data = True
                break

    # Sort people who've been trained to the top then by nickname
    form.volunteers = sorted(
        form.volunteers,
        key=lambda f: (-1 if f.trained.data else 1, f._volunteer.nickname),
    )

    return render_template("volunteer/training/train_users.html", role=role, form=form)
