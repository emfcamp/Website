from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from flask import (
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask import current_app as app
from flask.typing import ResponseReturnValue
from flask_login import current_user
from icalendar import Calendar, Event
from sqlalchemy.orm import joinedload

from apps.users.calendar import CalendarDict, CalendarEntry, fetch_events
from main import db, get_or_404
from models import naive_utcnow
from models.user import User, generate_api_token
from models.volunteer.role import Role
from models.volunteer.shift import Shift, ShiftEntry
from models.volunteer.venue import VolunteerVenue
from models.volunteer.volunteer import Volunteer

from ..common import feature_flag, get_next_url
from ..config import config
from ..schedule import event_tz
from . import v_admin_required, v_user_required, volunteer


def _get_roles_with_user_data(user):
    roles = Role.get_all()
    volunteer = Volunteer.get_for_user(user)
    res = []

    for r in roles:
        to_add = r.to_dict()
        to_add["is_interested"] = r in volunteer.interested_roles
        to_add["is_trained"] = not r.requires_training or r in volunteer.trained_roles

        res.append(to_add)

    return res


def _get_conflicts(shift: Shift, calendar: Sequence[CalendarEntry]) -> tuple[str, list[CalendarDict]]:
    """Return (primary_conflict_type, conflict_details) for a shift.

    primary_conflict_type is the highest-priority conflict type (for CSS), or ""
    if there are no conflicts. conflict_details is a list of dicts describing
    each conflicting event.
    """
    conflicts = sorted(
        [event for event in calendar if event.overlaps_with(shift.start, shift.end)],
        key=lambda c: c.conflict_priority,
    )
    if not conflicts:
        return "", []

    details = [c.to_dict() for c in conflicts]
    return conflicts[0].type, details


def redirect_next_or_schedule(message: str | None = None) -> ResponseReturnValue:
    """
    Set the flash if `message` is set, then redirect either to the URL in the
    `next` form field, or if that doesn't exist to the schedule page.
    """
    if message is not None:
        flash(message)

    next = get_next_url(url_for(".schedule"))

    return redirect(next)


@volunteer.route("/public-dashboard")
@feature_flag("VOLUNTEERS_SCHEDULE")
def public_dashboard():
    days = int(request.args.get("days", 1))
    refresh = int(request.args.get("refresh", 0))
    now = datetime.now()
    shifts = (
        db.session.query(Shift)
        .where(
            Shift.end > datetime.now(),
            Shift.current_count < Shift.max_needed,
            Shift.start < now + timedelta(days=days),
        )
        .order_by(Shift.start, Shift.venue_id)
        .all()
    )

    return render_template(
        "volunteer/public_dashboard.html",
        shifts=shifts,
        now=now,
        soon=now + timedelta(hours=1),
        refresh=refresh,
    )


@volunteer.route("/schedule")
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_user_required
def schedule():
    current_volunteer = Volunteer.get_for_user(current_user)
    earliest, latest = Shift.earliest_and_latest_in_range(*current_volunteer.permitted_shift_times)
    if earliest is None or latest is None:
        abort(404)
    dates = [earliest.date() + timedelta(days=i) for i in range((latest.date() - earliest.date()).days + 1)]

    if naive_utcnow().date() < dates[0]:
        default_day = dates[0]
    elif naive_utcnow().date() > dates[1]:
        default_day = dates[1]
    else:
        default_day = datetime.now().date()

    requested_date = request.args.get("day", default=None)
    if requested_date:
        active_day = datetime.fromisoformat(requested_date).date()
    else:
        active_day = default_day

    shifts = Shift.get_all_for_day(active_day)
    if len(shifts) == 0:
        # If there's no shifts nothing can conflict, so don't bother looking.
        user_calendar = []
    else:
        user_calendar = fetch_events(current_user, shifts[0].start, shifts[-1].end)

    by_time = defaultdict(lambda: [])

    for s in shifts:
        hour_key = s.start.strftime("%H:%M")
        to_add = s.to_localtime_dict()
        to_add["conflicts_with"], to_add["conflicts_detail"] = _get_conflicts(s, user_calendar)
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
        dates=dates,
        active_day=active_day,
        untrained_roles=untrained_roles,
        buildup_volunteer=current_volunteer.registered_for_buildup,
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

    title = f"EMF {config.event_year} Volunteer Shifts for {user.name}"

    cal = Calendar()
    cal.add("summary", title)
    cal.add("X-WR-CALNAME", title)
    cal.add("X-WR-CALDESC", title)
    cal.add("version", "2.0")

    shifts = (
        Shift.query.select_from(ShiftEntry)
        .join(Shift.entries.and_(ShiftEntry.user == user))
        .options(joinedload(Shift.venue), joinedload(Shift.role))
    ).all()

    for shift in shifts:
        cal_event = Event()
        cal_event.add("uid", f"{config.event_year}-{shift.id}")
        cal_event.add("summary", f"{shift.role.name} at {shift.venue.name}")
        cal_event.add("location", shift.venue.name)
        cal_event.add("dtstart", event_tz.localize(shift.start))
        cal_event.add("dtend", event_tz.localize(shift.end))
        cal.add_component(cal_event)

    return Response(cal.to_ical(), mimetype="text/calendar")


@volunteer.route("/shift/<shift_id>", methods=["GET"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_admin_required
def shift(shift_id):
    shift = get_or_404(db, Shift, shift_id)
    all_volunteers = Volunteer.query.order_by(Volunteer.nickname).all()

    return render_template("volunteer/shift.html", shift=shift, all_volunteers=all_volunteers)


@volunteer.route("/shift/<shift_id>/sign-up", methods=["POST"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_user_required
def shift_sign_up(shift_id):
    shift = get_or_404(db, Shift, shift_id)
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

    db.session.add(ShiftEntry(user=user, shift=shift))
    db.session.commit()

    return redirect_next_or_schedule(f"Signed up {shift.role.name} shift")


@volunteer.route("/shift/<shift_id>/cancel", methods=["POST"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_user_required
def shift_cancel(shift_id):
    shift = get_or_404(db, Shift, shift_id)

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
    shift = get_or_404(db, Shift, shift_id)
    session["recipients"] = [u.volunteer.id for u in shift.volunteers]
    return redirect(url_for("volunteer_admin_notify.main"))
