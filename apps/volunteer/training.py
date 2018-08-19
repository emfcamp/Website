# coding=utf-8

from flask import render_template, flash, current_app as app, redirect, url_for

from wtforms import SubmitField, BooleanField, FormField, FieldList
from wtforms.validators import Required

from main import db

from models.volunteer.role import Role
from models.volunteer.volunteer import Volunteer

from . import v_admin_required, volunteer
from ..common.forms import Form, HiddenIntegerField


class VolunteerSelectForm(Form):
    volunteer_id = HiddenIntegerField('Volunteer ID', [Required()])
    trained = BooleanField('Volunteer')


class TrainingForm(Form):
    volunteers = FieldList(FormField(VolunteerSelectForm))
    submit = SubmitField('Train these volunteers.')

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


@volunteer.route('/train-users')
@v_admin_required
def select_training():
    return render_template('volunteer/training/select_training.html', roles=Role.get_all())


@volunteer.route('/train-users/<role_id>', methods=['GET', 'POST'])
@v_admin_required
def train_users(role_id):
    role = Role.get_by_id(role_id)
    form = TrainingForm()

    form.add_volunteers(Volunteer.get_all())

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
        flash('Trained %d volunteers' % changes)
        app.logger.info('Trained %d volunteers' % changes)

        return redirect(url_for('.train_users', role_id=role_id))

    for v in role.trained_volunteers:
        for f in form.volunteers:
            if f.volunteer_id.data == v.id:
                f.trained.data = True
                break

    # Sort people who've been trained to the top then by nickname
    form.volunteers = sorted(form.volunteers, key=lambda f: (-1 if f.trained.data else 1, f._volunteer.nickname))

    return render_template('volunteer/training/train_users.html', role=role, form=form)

