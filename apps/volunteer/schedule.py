from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta

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
from sqlalchemy import select
from sqlalchemy.orm import joinedload, with_parent

from apps.cfp.date import CONTENT_DAY_START
from apps.users.calendar import CalendarDict, CalendarEntry, fetch_events
from main import db, get_or_404
from models.user import User, generate_api_token
from models.volunteer.role import Role
from models.volunteer.shift import Shift, ShiftEntry, ShiftEntryState
from models.volunteer.venue import VolunteerVenue
from models.volunteer.volunteer import Volunteer

from ..common import feature_enabled, feature_flag, get_next_url
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


def _active_day(permitted: list[date]) -> date:
    now = datetime.now(event_tz)
    day = now.date()

    # Days outside of the permitted range are clamped to that range.
    if day < permitted[0]:
        return permitted[0]

    if day > permitted[1]:
        return permitted[1]

    # We're at a festival. If the sun isn't up it's not tomorrow yet, show what
    # is technically the previous day.
    if now.hour < CONTENT_DAY_START.hour:
        return day - timedelta(days=1)

    return day


@volunteer.route("/schedule")
@v_user_required
def schedule():
    # Volunteer admins and role admins can see the schedule at any time.
    is_admin = (
        current_user.has_permission("admin")
        or current_user.has_permission("volunteer_admin")
        or len(current_user.administered_roles) > 0
    )
    if not feature_enabled("VOLUNTEERS_SCHEDULE") and not is_admin:
        abort(404)

    current_volunteer = Volunteer.get_for_user(current_user)
    earliest, latest = Shift.earliest_and_latest_in_range(*current_volunteer.permitted_shift_times)
    if earliest is None or latest is None:
        abort(404)
    dates = [earliest.date() + timedelta(days=i) for i in range((latest.date() - earliest.date()).days + 1)]

    requested_date = request.args.get("day", default=None)
    if requested_date:
        active_day = datetime.fromisoformat(requested_date).date()
    else:
        active_day = _active_day(dates)

    shifts = Shift.get_all_for_day(active_day, include_unfinalised=is_admin)
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
        is_admin=is_admin,
        owned_roles=current_volunteer.administered_role_ids,
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


def _get_shift_entry_for_user(shift_id: int, user: User) -> ShiftEntry:
    """Gets a ShiftEntry and ensures it belongs to a specific user."""
    shift_entry = db.session.execute(
        select(ShiftEntry)
        .where(ShiftEntry.user_id == user.id)
        .where(ShiftEntry.shift_id == shift_id)
        .join(ShiftEntry.shift)
    ).scalar_one_or_none()
    if shift_entry is None:
        raise abort(404)

    return shift_entry


@volunteer.route("/set-time", methods=["GET"])
@v_admin_required
def set_time() -> ResponseReturnValue:
    """Sets `now` in the session to the value of request.args["now"].

    If the arg isn't set deletes the value from the session and reverts to using
    realtime. Intended purely for testing purposes.
    """
    if not config.get("DEBUG"):
        # We only allow mocking the time in debug mode because it could be used to
        # bypass time checks on volunteer checkin.
        abort(404)

    provided_time = request.args.get("now", None)
    if provided_time:
        session["now"] = provided_time
    else:
        del session["now"]

    return redirect_next_or_schedule(f"Time set to {provided_time}")


def _now() -> datetime:
    """Allow setting a time as 'now', falling back to datetime.now()."""
    injected_time = session.get("now", None)
    if not config.get("DEBUG") or not injected_time:
        return datetime.now()

    return datetime.strptime(injected_time, "%Y-%m-%dT%H:%M:%S")


@volunteer.route("/self-checkin/venue/<venue_id>", methods=["GET"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_user_required
def self_checkin(venue_id: int) -> ResponseReturnValue:
    """Allow a user to check themselves into a shift at a specific venue.

    Intended to be accessed via QR codes in those venues. When loaded we'll check
    whether the user has a scheduled shift in this venue either starting within
    the next 15 minutes or currently in progress and if so allow them to mark
    themselves as arrived.

    If they're already marked as arrived then they'll be able to mark themselves
    as either abandoning the shift, or if we're within 15 minutes of shift end
    that they've completed the shift.
    """

    now = _now()
    venue = get_or_404(db, VolunteerVenue, venue_id)
    shift_entries = (
        db.session.execute(
            select(ShiftEntry)
            .where(with_parent(current_user, User.shift_entries))
            .join(ShiftEntry.shift)
            .where(Shift.venue == venue)
            .where(Shift.end >= now - timedelta(hours=2))
            .order_by(Shift.start)
        )
        .scalars()
        .all()
    )

    # Segment into shifts that can be checked into and shifts that can't yet.
    checked_in_roles_with_notes: list[Role] = []
    open_shift_entries: list[ShiftEntry] = []
    upcoming_shift_entries: list[ShiftEntry] = []
    previous_shift_entries: list[ShiftEntry] = []

    for entry in shift_entries:
        if entry.state == ShiftEntryState.ARRIVED:
            open_shift_entries.append(entry)
            role = entry.shift.role
            if role.role_notes or role.instructions_url:
                checked_in_roles_with_notes.append(role)

        elif entry.state == ShiftEntryState.SIGNED_UP:
            if entry.shift.start <= now + timedelta(minutes=15):
                open_shift_entries.append(entry)
            else:
                upcoming_shift_entries.append(entry)

        else:
            previous_shift_entries.append(entry)

    return render_template(
        "volunteer/self_checkin.html",
        venue=venue,
        checked_in_roles_with_notes=checked_in_roles_with_notes,
        open_shift_entries=open_shift_entries,
        upcoming_shift_entries=upcoming_shift_entries,
        previous_shift_entries=previous_shift_entries,
        now=now,
    )


@volunteer.route("/self-checkin/arrived", methods=["POST"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_user_required
def self_checkin_arrived() -> ResponseReturnValue:
    shift_entry_id = int(request.form["shift_id"])
    shift_entry = _get_shift_entry_for_user(shift_entry_id, current_user)
    if not shift_entry.eligible_for_checkin_at(_now()):
        return redirect_next_or_schedule("Unexpected volunteer in bagging area.")

    shift_entry.set_state(ShiftEntryState.ARRIVED)
    db.session.commit()

    return redirect_next_or_schedule("You're checked in.")


@volunteer.route("/self-checkin/complete", methods=["POST"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_user_required
def self_checkin_complete() -> ResponseReturnValue:
    shift_entry_id = int(request.form["shift_id"])
    shift_entry = _get_shift_entry_for_user(shift_entry_id, current_user)
    if not shift_entry.eligible_for_completion_at(_now()):
        return redirect_next_or_schedule("Unexpected volunteer in bagging area.")

    shift_entry.set_state(ShiftEntryState.COMPLETED)
    db.session.commit()

    return redirect_next_or_schedule("Thanks for volunteering!")


@volunteer.route("/self-checkin/abandon", methods=["POST"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_user_required
def self_checkin_abandon() -> ResponseReturnValue:
    shift_entry_id = int(request.form["shift_id"])
    shift_entry = _get_shift_entry_for_user(shift_entry_id, current_user)
    if not shift_entry.eligible_for_checkout_at(_now()):
        return redirect_next_or_schedule("Unexpected volunteer in bagging area.")

    shift_entry.set_state(ShiftEntryState.ABANDONED)
    db.session.commit()

    return redirect_next_or_schedule("You've checked out.")


@volunteer.route("/shift/<shift_id>/contact", methods=["GET"])
@feature_flag("VOLUNTEERS_SCHEDULE")
@v_admin_required
def shift_contact(shift_id):
    shift = get_or_404(db, Shift, shift_id)
    session["recipients"] = [u.volunteer.id for u in shift.volunteers]
    return redirect(url_for("volunteer_admin_notify.main"))
