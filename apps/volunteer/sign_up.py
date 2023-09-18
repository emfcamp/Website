from flask import (
    current_app as app,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    render_template_string,
)
from markupsafe import Markup
from flask_login import current_user
from wtforms import StringField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Email, ValidationError

from main import db
from models.volunteer import Volunteer as VolunteerUser
from models.user import User

from . import volunteer, v_user_required
from ..common.forms import Form, TelField
from ..common import create_current_user, feature_flag


class VolunteerSignUpForm(Form):
    nickname = StringField("Name", [DataRequired()])
    volunteer_email = StringField("Email", [Email(), DataRequired()])
    over_18 = BooleanField("I'm at least 18 years old")
    volunteer_phone = TelField("Phone", min_length=3)
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
    return volunteer


@volunteer.route("/sign-up", methods=["GET", "POST"])
@feature_flag("VOLUNTEERS_SIGNUP")
def sign_up():
    form = VolunteerSignUpForm()

    if current_user.is_authenticated and VolunteerUser.get_for_user(current_user):
        return redirect(url_for(".schedule"))

    if request.method != "POST" and current_user.is_authenticated:
        form.volunteer_email.data = current_user.email
        form.nickname.data = current_user.name
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

    if form.validate_on_submit():
        update_volunteer_from_form(volunteer, form)
        db.session.commit()
        flash("Your details have been updated", "info")
        return redirect(url_for(".account"))

    return render_template("volunteer/account.html", user=current_user, form=form)
