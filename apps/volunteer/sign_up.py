from flask import (
    current_app as app,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    Markup,
    render_template_string,
)

from datetime import timedelta
from flask_login import current_user
from wtforms import StringField, SelectField, SubmitField, BooleanField
from wtforms.validators import Required, Email, ValidationError, Optional

from pendulum import period

from main import db
from models import event_start, event_end
from models.volunteer import Volunteer as VolunteerUser
from models.user import User

from . import volunteer, v_user_required
from ..common.forms import Form
from ..common import create_current_user, feature_flag


class VolunteerSignUpForm(Form):
    nickname = StringField("Name", [Required()])
    volunteer_email = StringField("Email", [Email(), Required()])
    over_18 = BooleanField("I'm at least 18 years old")
    volunteer_phone = StringField("Phone", [Required()])
    arrival = SelectField("Arrival")
    departure = SelectField("Departure")
    allow_comms = BooleanField(
        "May we send you messages during the event?", [Optional()]
    )
    sign_up = SubmitField("Sign Up")
    save = SubmitField("Save")

    def validate_volunteer_email(form, field):
        if current_user.is_anonymous and User.does_user_exist(field.data):
            field.was_duplicate = True
            volunteer_url = url_for(".sign_up")

            msg = Markup(
                render_template_string(
                    """You already have an account.
                Please <a href="{{ url }}" target="_new">click here</a> to log in.""",
                    url=url_for("users.login", next=volunteer_url, email=field.data),
                )
            )

            raise ValidationError(msg)


def update_volunteer_from_form(volunteer, form):
    volunteer.nickname = form.nickname.data
    volunteer.volunteer_email = form.volunteer_email.data
    volunteer.volunteer_phone = form.volunteer_phone.data
    volunteer.over_18 = form.over_18.data
    volunteer.planned_arrival = form.arrival.data
    volunteer.planned_departure = form.departure.data
    volunteer.allow_comms_during_event = form.allow_comms.data
    return volunteer


@volunteer.route("/sign-up", methods=["GET", "POST"])
@feature_flag("VOLUNTEERS_SIGNUP")
def sign_up():
    form = VolunteerSignUpForm()
    form.arrival.choices = generate_arrival_options()
    form.departure.choices = generate_departure_options()

    if current_user.is_authenticated and VolunteerUser.get_for_user(current_user):
        return redirect(url_for(".account"))

    if request.method != "POST" and current_user.is_authenticated:
        form.volunteer_email.data = current_user.email
        form.nickname.data = current_user.name
        form.volunteer_phone.data = current_user.phone
        # Can't try to process age, as that's only submitted as part of the outreach questions

    if form.validate_on_submit():
        if current_user.is_anonymous:
            create_current_user(form.volunteer_email.data, form.nickname.data)

        new_volunteer = VolunteerUser()
        new_volunteer.user_id = current_user.id
        new_volunteer = update_volunteer_from_form(new_volunteer, form)
        db.session.add(new_volunteer)

        # On sign up give user 'volunteer' permission (+ managers etc.)
        current_user.grant_permission("volunteer:user")

        db.session.commit()
        app.logger.info("Add volunteer: %s", new_volunteer)
        flash("Thank you for signing up!", "message")
        return redirect(url_for(".choose_role"))

    # Set form default arrival and departure dates to be start and end
    form.arrival.data = event_start().strftime("%F")
    form.departure.data = event_end().strftime("%F")

    return render_template("volunteer/sign-up.html", user=current_user, form=form)


@volunteer.route("/account", methods=["GET", "POST"])
@feature_flag("VOLUNTEERS_SIGNUP")
@v_user_required
def account():
    if current_user.is_anonymous:
        return redirect(url_for(".sign_up"))

    volunteer = VolunteerUser.get_for_user(current_user)
    if volunteer is None:
        return redirect(url_for(".sign_up"))

    form = VolunteerSignUpForm(obj=volunteer)
    form.arrival.choices = generate_arrival_options()
    form.departure.choices = generate_departure_options()

    if form.validate_on_submit():
        update_volunteer_from_form(volunteer, form)
        db.session.commit()
        flash("Your details have been updated", "info")
        return redirect(url_for(".account"))

    form.arrival.data = volunteer.planned_arrival.strftime("%Y-%m-%d")
    form.departure.data = volunteer.planned_departure.strftime("%Y-%m-%d")
    form.allow_comms.data = volunteer.allow_comms_during_event

    return render_template("volunteer/account.html", user=current_user, form=form)


def generate_arrival_options():
    choices = []

    # Work out our first arrival based on config
    first_arrival = event_start() - timedelta(app.config["ARRIVAL_DAYS"])

    # Work out dates between first arrival and end of the event
    choices = generate_day_options(first_arrival, event_end())

    # Replace first array element with first date and 'or earlier'
    choices[0] = (
        first_arrival.strftime("%F"),
        first_arrival.strftime("%A %-d %B or earlier"),
    )

    return choices


def generate_departure_options():
    choices = []

    # Work out our last arrival based on config
    last_departure = event_end() + timedelta(app.config["DEPARTURE_DAYS"])

    # Work out dates between start of the event and last departure
    choices = generate_day_options(event_start(), last_departure)

    # Replace last array element with the last date and 'or later'
    choices[len(choices) - 1] = (
        last_departure.strftime("%F"),
        last_departure.strftime("%A %-d %B or later"),
    )

    return choices


def generate_day_options(start, stop):
    choices = []

    # Work out dates between start and stop
    days = period(start, stop)

    # Add each date to the list
    for d in days:
        choices.append((d.strftime("%F"), d.strftime("%A %-d %B")))

    return choices
