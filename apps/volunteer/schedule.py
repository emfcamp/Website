# coding=utf-8
import pendulum
from icalendar import Calendar, Event
from datetime import datetime
from flask import render_template, request, redirect, url_for, flash, abort, session, Response
from flask import current_app as app
from collections import defaultdict
from flask_login import current_user
from sqlalchemy.orm import joinedload

from main import db
from models import event_year
from models.user import User, generate_api_token

from models.volunteer.role import Role
from models.volunteer.venue import VolunteerVenue
from models.volunteer.shift import Shift, ShiftEntry
from models.volunteer.volunteer import Volunteer
from models import config_date

from ..schedule import event_tz
from ..users import get_next_url
from ..common import feature_flag
from . import volunteer, v_user_required, v_admin_required


def _get_roles_with_user_data(user):
    roles = Role.get_all()
    volunteer = Volunteer.get_for_user(user)
    res = []

    for r in roles:
        to_add = r.to_dict()
        to_add["is_interested"] = r in volunteer.interested_roles
        to_add["is_trained"] = r in volunteer.trained_roles

        res.append(to_add)

    return res


def redirect_next_or_schedule(message: str | None = None):
    """
    Set the flash if `message` is set, then redirect either to the URL in the
    `next` form field, or if that doesn't exist to the schedule page.
    """
    if message is not None:
        flash(message)

    next = get_next_url(url_for(".schedule"))

    return redirect(next)


@volunteer.route("/schedule")
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_user_required
def schedule():
    if datetime.utcnow() < config_date("EVENT_START"):
        default_day = "wed"
    elif datetime.utcnow() > config_date("EVENT_END"):
        default_day = "mon"
    else:
        default_day = pendulum.now().strftime("%a").lower()
    active_day = request.args.get("day", default=default_day)

    shifts = Shift.get_all_for_day(active_day)

    by_time = defaultdict(lambda: [])

    for s in shifts:
        hour_key = s.start.strftime("%H:%M")

        to_add = s.to_localtime_dict()
        to_add["sign_up_url"] = url_for(".shift", shift_id=to_add["id"])
        to_add["is_user_shift"] = current_user in s.volunteers
        by_time[hour_key].append(to_add)

    roles = _get_roles_with_user_data(current_user)
    venues = VolunteerVenue.get_all()

    untrained_roles = [
        r for r in roles if r["is_interested"] and r["requires_training"] and not r["is_trained"]
    ]

    token = generate_api_token(app.config["SECRET_KEY"], current_user.id)

    return render_template(
        "volunteer/schedule.html",
        roles=roles,
        venues=venues,
        all_shifts=by_time,
        active_day=active_day,
        untrained_roles=untrained_roles,
        token=token,
    )


@volunteer.route("/schedule.ical")
@volunteer.route("/schedule.ics")
@feature_flag("VOLUNTEERS_SCHEDULE")
def schedule_ical():
    code = request.args.get("token", None)
    user = None
    if code:
        user = User.get_by_api_token(app.config.get("SECRET_KEY"), str(code))
    if not current_user.is_anonymous:
        user = current_user
    if not user:
        abort(404)

    title = "EMF {} Volunteer Shifts for {}".format(event_year(), user.name)

    cal = Calendar()
    cal.add("summary", title)
    cal.add("X-WR-CALNAME", title)
    cal.add("X-WR-CALDESC", title)
    cal.add("version", "2.0")

    shifts = (Shift.query
            .select_from(ShiftEntry)
            .join(Shift.entries.and_(ShiftEntry.user == user))
            .options(
                joinedload(Shift.venue),
                joinedload(Shift.role)
            )).all()

    for shift in shifts:
        cal_event = Event()
        cal_event.add("uid", "%s-%s" % (event_year(), shift.id))
        cal_event.add("summary", "%s at %s" % (shift.role.name, shift.venue.name))
        cal_event.add("location", shift.venue.name)
        cal_event.add("dtstart", event_tz.localize(shift.start))
        cal_event.add("dtend", event_tz.localize(shift.end))
        cal.add_component(cal_event)

    return Response(cal.to_ical(), mimetype="text/calendar")


@volunteer.route("/shift/<shift_id>", methods=["GET"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_admin_required
def shift(shift_id):
    shift = Shift.query.get_or_404(shift_id)
    all_volunteers = Volunteer.query.order_by(Volunteer.nickname).all()

    return render_template("volunteer/shift.html", shift=shift, all_volunteers=all_volunteers)


@volunteer.route("/shift/<shift_id>/sign-up", methods=["POST"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_user_required
def shift_sign_up(shift_id):
    shift = Shift.query.get_or_404(shift_id)
    if current_user.has_permission("volunteer:admin") and "user_id" in request.form:
        user = User.query.get(request.form["user_id"])
    else:
        user = current_user

    shift_entry = ShiftEntry.query.filter_by(user_id=user.id, shift_id=shift.id).first()
    if shift_entry:
        # User is already signed up for this shift, so just redirect back saying
        # they've been signed up.
        return redirect_next_or_schedule(f"Signed up for {shift.role.name} shift")

    if shift.current_count >= shift.max_needed:
        return redirect_next_or_schedule("This shift is already full. You have not been signed up.")

    if shift.role.requires_training and shift.role not in Volunteer.get_for_user(current_user).trained_roles:
        return redirect_next_or_schedule("You must complete training before you can sign up for this shift.")

    for shift_entry in user.shift_entries:
        if shift.is_clash(shift_entry.shift):
            clashing_shift = shift_entry.shift
            clash_role = clashing_shift.role.name
            clash_time = clashing_shift.start.strftime("%H:%M")

            return redirect_next_or_schedule(
                f"This shift clashes with your {clash_role} shift at {clash_time}, you have not been signed up."
            )

    shift.entries.append(ShiftEntry(user=user, shift=shift))
    db.session.commit()

    return redirect_next_or_schedule(f"Signed up {shift.role.name} shift")


@volunteer.route("/shift/<shift_id>/cancel", methods=["POST"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_user_required
def shift_cancel(shift_id):
    shift = Shift.query.get_or_404(shift_id)

    user = current_user
    shift_entry = ShiftEntry.query.filter_by(user_id=user.id, shift_id=shift.id).first()
    if shift_entry:
        db.session.delete(shift_entry)
        db.session.commit()

    return redirect_next_or_schedule(f"{shift.role.name} shift cancelled")


@volunteer.route("/shift/<shift_id>/contact", methods=["GET"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_admin_required
def shift_contact(shift_id):
    shift = Shift.query.get_or_404(shift_id)
    session["recipients"] = [u.volunteer.id for u in shift.volunteers]
    return redirect(url_for("volunteer_admin_notify.main"))
