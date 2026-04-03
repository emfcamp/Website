from datetime import datetime, timedelta
from itertools import groupby

from decorator import decorator
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
from flask.typing import ResponseReturnValue
from flask_login import current_user
from sqlalchemy import select

from apps.volunteer import v_user_required, volunteer
from main import db, get_or_404
from models.user import User
from models.volunteer.role import Role
from models.volunteer.shift import (
    Shift,
    ShiftEntry,
    ShiftEntryState,
    ShiftEntryStateException,
)


@volunteer.route("/role-admin", methods=["GET"])
@v_user_required
def role_admin_index():
    roles = []
    if (
        current_user.has_permission("admin")
        or current_user.has_permission("volunteer:manager")
        or current_user.has_permission("volunteer:admin")
    ):
        roles = Role.query.order_by("name").all()
    else:
        administered_ids = current_user.administered_role_ids
        roles = Role.query.filter(Role.id.in_(administered_ids)).order_by("name").all()

    if len(roles) == 0:
        flash("You're not an admin for any roles.")
        return redirect(url_for(".choose_role"))

    if len(roles) == 1:
        return redirect(url_for(".role_admin", role_id=roles[0].id))

    return render_template(
        "volunteer/role_admin_index.html",
        roles={team: list(team_roles) for team, team_roles in groupby(roles, key=lambda r: r.team)},
    )


@decorator
def role_admin_required(f, *args, **kwargs):
    """Check that current user has permissions to be RoleAdmin for role.id that is first entry in args"""
    if current_user.is_authenticated:
        if int(args[0]) in current_user.volunteer.administered_role_ids or (
            current_user.has_permission("volunteer:admin") or current_user.has_permission("volunteer:manager")
        ):
            return f(*args, **kwargs)
        abort(404)
    return app.login_manager.unauthorized()


@volunteer.route("role/<int:role_id>/admin")
@role_admin_required
def role_admin(role_id):
    # Allow mocking the time for testing.
    if "now" in request.args:
        now = datetime.strptime(request.args["now"], "%Y-%m-%dT%H:%M")
    else:
        now = datetime.now()

    limit = int(request.args.get("limit", "5"))
    offset = int(request.args.get("offset", "0"))
    role = get_or_404(db, Role, role_id)
    cutoff = now - timedelta(minutes=30)
    shifts = (
        Shift.query.filter_by(role=role)
        .filter(Shift.end >= cutoff)
        .order_by(Shift.end)
        .offset(offset)
        .limit(limit)
        .all()
    )

    active_shift_entries = (
        ShiftEntry.query.filter(ShiftEntry.state == ShiftEntryState.ARRIVED)
        .join(ShiftEntry.shift)
        .filter(Shift.role_id == role.id)
        .all()
    )
    pending_shift_entries = (
        ShiftEntry.query.join(ShiftEntry.shift)
        .filter(
            Shift.start <= now - timedelta(minutes=15),
            Shift.role == role,
            ShiftEntry.state == ShiftEntryState.SIGNED_UP,
        )
        .all()
    )

    return render_template(
        "volunteer/role_admin.html",
        role=role,
        shifts=shifts,
        active_shift_entries=active_shift_entries,
        pending_shift_entries=pending_shift_entries,
        now=now,
        offset=offset,
        limit=limit,
    )


@volunteer.route("role/<int:role_id>/set-state/<int:shift_id>/<int:user_id>", methods=["POST"])
@role_admin_required
def set_state(role_id: int, shift_id: int, user_id: int) -> ResponseReturnValue:
    state = request.form["state"]

    se = (
        db.session.execute(
            select(ShiftEntry).where(ShiftEntry.shift_id == shift_id, ShiftEntry.user_id == user_id)
        )
        .scalars()
        .first()
    )
    if se is None:
        abort(404)
    if se.state != state:
        try:
            se.set_state(state)
        except ShiftEntryStateException:
            flash(f"{state} is not a valid state for this shift.")
        else:
            db.session.commit()

    return redirect(url_for(".role_admin", role_id=role_id))


@volunteer.route("role/<int:role_id>/<int:shift_id>", methods=["POST"])
@role_admin_required
def update_shift(role_id: int, shift_id: int) -> ResponseReturnValue:
    shift = get_or_404(db, Shift, shift_id)
    shift.min_needed = int(request.form["min_needed"])
    shift.max_needed = int(request.form["max_needed"])
    db.session.add(shift)
    db.session.commit()

    flash("Shift requirements updated.")
    return redirect(url_for(".role_admin", role_id=role_id, _anchor=f"shift-{shift.id}"))


@volunteer.route("role/<int:role_id>/volunteers")
@role_admin_required
def role_volunteers(role_id):
    role = get_or_404(db, Role, role_id)
    interested = User.query.join(User.interested_roles).filter(Role.id == role_id).all()
    entries = ShiftEntry.query.join(ShiftEntry.shift).filter(Shift.role_id == role_id).all()
    signed_up = list(set([se.user.volunteer for se in entries]))
    completed = list(set([se.user.volunteer for se in entries if se.state == "completed"]))
    return render_template(
        "volunteer/role_volunteers.html",
        role=role,
        interested=interested,
        signed_up=signed_up,
        completed=completed,
    )
