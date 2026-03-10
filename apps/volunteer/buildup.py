from datetime import datetime

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask import (
    current_app as app,
)
from flask_login import current_user, login_required
from sqlalchemy import select
from werkzeug.wrappers.response import Response
from wtforms import BooleanField, DateTimeLocalField, StringField, SubmitField
from wtforms.validators import DataRequired, InputRequired

from apps.common import get_next_url
from main import db
from models.volunteer.buildup import BuildupSignupKey, BuildupVolunteer, buildup_start, teardown_end
from models.volunteer.volunteer import Volunteer as VolunteerUser

from ..common import create_current_user
from ..common.forms import Form
from . import volunteer
from .sign_up import VolunteerSignUpForm, update_volunteer_from_form


class BuildupSignUpForm(Form):
    arrival_date = DateTimeLocalField(
        "Arrival Date",
        [
            InputRequired(),
        ],
        format="%Y-%m-%dT%H:%M",
    )
    departure_date = DateTimeLocalField(
        "Departure Date",
        [
            InputRequired(),
        ],
        format="%Y-%m-%dT%H:%M",
    )

    emergency_contact = StringField(
        "Emergency Contact",
        [
            InputRequired(),
        ],
    )

    health_and_safety_briefing = BooleanField(
        "I have read and agree to follow the rules in the Safety on Site briefing above",
        [
            DataRequired(),
        ],
    )

    save = SubmitField("Confirm buildup/teardown attendance")

    def validate(self, *args, **kwargs):
        rv = super().validate(*args, **kwargs)
        if not rv:
            return False

        if self.arrival_date.data > self.departure_date.data:
            self.departure_date.errors.append(
                "You must depart after you arrive. Violating the laws of causality is not permitted."
            )
            return False
        return True


def update_buildup_volunteer_from_form(buv: BuildupVolunteer, form: BuildupSignUpForm) -> BuildupVolunteer:
    if form.arrival_date.data:
        buv.arrival_date = form.arrival_date.data
    if form.departure_date.data:
        buv.departure_date = form.departure_date.data
    if form.emergency_contact.data:
        buv.emergency_contact = form.emergency_contact.data
    if form.health_and_safety_briefing.data:
        buv.acked_health_and_safety_briefing_at = datetime.now()
    return buv


def _buildup_register(show_form_on_success: bool = False, key: BuildupSignupKey | None = None) -> str | None:
    volunteer = current_user.is_authenticated and VolunteerUser.get_for_user(current_user)
    passed_validation = request.method == "POST"
    volunteer_form = VolunteerSignUpForm(prefix="v", obj=volunteer)
    if not volunteer and request.method == "GET" and current_user.is_authenticated:
        volunteer_form.volunteer_email.data = current_user.email
        volunteer_form.nickname.data = current_user.name

    volunteer_form.over_18.validators = [
        DataRequired(message="Sorry, but you must be over 18 to be on the field during buildup and teardown")
    ]
    if volunteer_form.validate_on_submit():
        if volunteer:
            volunteer = update_volunteer_from_form(volunteer, volunteer_form)
            db.session.add(volunteer)
        else:
            if not volunteer_form.volunteer_email.data or not volunteer_form.nickname.data:
                abort(400)
            if current_user.is_anonymous:
                create_current_user(volunteer_form.volunteer_email.data, volunteer_form.nickname.data)
            new_volunteer = VolunteerUser()
            new_volunteer.user_id = current_user.id
            new_volunteer = update_volunteer_from_form(new_volunteer, volunteer_form)
            db.session.add(new_volunteer)
            volunteer = new_volunteer

        current_user.grant_permission("volunteer:user")
    else:
        passed_validation = False

    # Now the buildup form
    buv = current_user.is_authenticated and BuildupVolunteer.get_for_user(current_user)
    buildup_form = BuildupSignUpForm(prefix="b", obj=buv)
    if buv and buv.acked_health_and_safety_briefing_at:
        buildup_form.health_and_safety_briefing.data = True
    if buildup_form.validate_on_submit():
        buv = current_user.is_authenticated and BuildupVolunteer.get_for_user(current_user)
        if buv:
            buv = update_buildup_volunteer_from_form(buv, buildup_form)
            db.session.add(buv)
        else:
            new_buv = BuildupVolunteer()
            new_buv.user_id = current_user.id
            if key:
                new_buv.team_name = key.team_name
            new_buv = update_buildup_volunteer_from_form(new_buv, buildup_form)
            db.session.add(new_buv)

        current_user.grant_permission("volunteer:buildup")
    else:
        passed_validation = False

    if passed_validation:
        db.session.commit()
        app.logger.info("Added new volunteer user %s through buildup flow", volunteer)
        flash("Thanks! Your buildup registration has been recorded.", "message")

        if not show_form_on_success:
            return None
    else:
        db.session.rollback()

    return render_template(
        "volunteer/buildup-sign-up.html",
        user=current_user,
        volunteer=volunteer,
        volunteer_form=volunteer_form,
        buildup_form=buildup_form,
        buildup_start=buildup_start(),
        teardown_end=teardown_end(),
    )


@volunteer.route("buildup/arrived/<secret>", methods=["GET", "POST"])
@login_required
def buildup_arrived(secret):
    if secret != app.config.get("BUILDUP_SECRET"):
        abort(404)

    buv = BuildupVolunteer.get_for_user(current_user)
    if not buv:
        if response := _buildup_register():
            return response
        # OK, they're registered now.
        buv = BuildupVolunteer.get_for_user(current_user)

    if not buv.recorded_on_site:
        buv.recorded_on_site = datetime.now()
        db.session.add(buv)
        db.session.commit()

    return render_template(
        "volunteer/buildup-arrived.html",
        user=current_user,
        is_buildup=datetime.now() < buildup_start(),
        buildup_signal_group=app.config.get("BUILDUP_SIGNAL_GROUP"),
    )


@volunteer.route("buildup", methods=["GET", "POST"])
@login_required
def buildup_amend():
    buv = BuildupVolunteer.get_for_user(current_user)
    if not buv and not current_user.has_permission("volunteer:buildup"):
        return abort(404)

    return _buildup_register(show_form_on_success=True)


@volunteer.route("buildup/register/<token>", methods=["GET", "POST"])
def buildup_register(token: str) -> Response | str:
    key = db.session.execute(
        select(BuildupSignupKey).where(BuildupSignupKey.token == token)
    ).scalar_one_or_none()
    if not key:
        abort(404)

    if current_user.is_authenticated and BuildupVolunteer.get_for_user(current_user):
        return redirect(url_for(".buildup_amend"))

    if response := _buildup_register(key=key):
        return response

    # They completed registration:
    return redirect(get_next_url(default=url_for(".buildup_amend")))
