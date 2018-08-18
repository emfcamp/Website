from flask import (
    current_app as app, render_template, redirect,
    url_for, flash, request,
)
from flask_login import current_user
from wtforms import (
    StringField, IntegerField, SelectField, SubmitField
)
from wtforms.validators import Required, Email

from pendulum import parse, period

from main import db
from models.volunteer.volunteer import Volunteer as VolunteerUser

from . import volunteer, v_user_required
from ..common.forms import Form
from ..common import create_current_user, feature_flag


def generate_day_options(start, stop):
    days = period(parse(start), parse(stop)).range('days', 1)
    return list([(d.strftime('%Y-%m-%d'), d.strftime('%A %-d %B')) for d in days])

ARRIVAL_CHOICES = generate_day_options('2018-08-27', '2018-09-02')
DEPARTURE_CHOICES = generate_day_options('2018-08-31', '2018-09-05')

class VolunteerSignUpForm(Form):
    name = StringField("Name", [Required()])
    email = StringField("Email", [Email(), Required()])
    age = IntegerField("Age", [Required()])
    phone_number = StringField("Phone Number", [Required()])
    arrival = SelectField("Arrival Day", choices=ARRIVAL_CHOICES)
    departure = SelectField("Departure Day", choices=DEPARTURE_CHOICES)
    submit = SubmitField('Save')

def update_volunteer_from_form(volunteer, form):
    volunteer.nickname = form.name.data
    volunteer.volunteer_email = form.email.data
    volunteer.volunteer_phone = form.phone_number.data
    volunteer.age = form.age.data
    volunteer.planned_arrival = form.arrival.data
    volunteer.planned_departure = form.departure.data
    return volunteer

@volunteer.route('/sign-up', methods=['GET', 'POST'])
@feature_flag('VOLUNTEERS_SIGNUP')
def sign_up():
    form = VolunteerSignUpForm()
    # On sign up give user 'volunteer' permission (+ managers etc.)

    if current_user.is_authenticated and VolunteerUser.get_for_user(current_user):
        return redirect(url_for('.account'))

    if request.method != 'POST' and current_user.is_authenticated:
        form.email.data = current_user.email
        form.name.data = current_user.name
        form.phone_number.data = current_user.phone

    if form.validate_on_submit():
        if current_user.is_anonymous:
            create_current_user(form.email.data, form.name.data)

        new_volunteer = VolunteerUser()
        new_volunteer.user_id = current_user.id
        new_volunteer = update_volunteer_from_form(new_volunteer, form)
        db.session.add(new_volunteer)

        current_user.grant_permission('volunteer:user')

        db.session.commit()
        app.logger.info('Add volunteer: %s', new_volunteer)
        flash('Thank you for signing up!', 'message')
        return redirect(url_for('.choose_role'))

    return render_template('volunteer/sign-up.html',
                           user=current_user,
                           form=form)

@volunteer.route('/account', methods=['GET', 'POST'])
@feature_flag('VOLUNTEERS_SIGNUP')
@v_user_required
def account():
    if current_user.is_anonymous:
        return redirect(url_for('.sign_up'))

    volunteer = VolunteerUser.get_for_user(current_user)
    if volunteer is None:
        return redirect(url_for('.sign_up'))

    form = VolunteerSignUpForm()

    if form.validate_on_submit():
        update_volunteer_from_form(volunteer, form)
        db.session.commit()
        flash('Saved', 'info')
        return redirect(url_for('.account'))


    form.name.data = volunteer.nickname
    form.email.data = volunteer.volunteer_email
    form.phone_number.data = volunteer.volunteer_phone
    form.age.data = volunteer.age
    form.arrival.data = volunteer.planned_arrival.strftime('%Y-%m-%d')
    form.departure.data = volunteer.planned_departure.strftime('%Y-%m-%d')

    return render_template('volunteer/account.html',
                            user=current_user, form=form)
