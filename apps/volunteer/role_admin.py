import re
from datetime import datetime, timedelta
from decimal import Decimal

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
from wtforms.fields import (
    BooleanField,
    DecimalField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import URL, InputRequired, NumberRange, Optional
from wtforms.widgets import TextArea

from apps.common.fields import HiddenIntegerField
from apps.common.forms import Form
from apps.volunteer import v_user_required, volunteer
from main import db, get_or_404
from models.volunteer.role import Role
from models.volunteer.shift import (
    Shift,
    ShiftEntry,
    ShiftEntryState,
    ShiftEntryStateException,
    ShiftTemplate,
)
from models.volunteer.venue import VolunteerVenue
from models.volunteer.volunteer import Volunteer


class ShiftTemplateForm(Form):
    id = HiddenIntegerField("ID", [Optional()])
    event_day = IntegerField(
        "Day",
        [InputRequired()],
        description="The event day for this block (-1, 0, 1, etc)",
    )
    start_time = TimeField(
        "Start Time",
        [InputRequired()],
        description="The time at which the first shift of the block should start. This will have the changeover time subtracted from it to allow volunteers to arrive and be briefed.",
    )
    end_time = TimeField(
        "End Time",
        [InputRequired()],
        description="The time at which the last shift of the block should end.",
    )
    venue_id = SelectField(
        "Venue", [InputRequired()], coerce=int, description="The venue volunteers should attend."
    )
    duration = IntegerField(
        "Duration",
        [InputRequired(), NumberRange(min=5)],
        description="The length of each shift, in minutes. Please speak to the volunteer team if you need this to be significantly more or less than two hours.",
    )
    changeover_time = IntegerField(
        "Changeover Time",
        [InputRequired()],
        description="The overlap between shifts, in minutes, to allow handover between volunteers.",
    )
    min_needed = IntegerField(
        "Min Volunteers", [InputRequired()], description="The minimum number of volunteers required."
    )
    max_needed = IntegerField(
        "Max Volunteers",
        [InputRequired()],
        description="The maximum number of volunteers you can make use of.",
    )
    multiplier = DecimalField(
        "Multiplier",
        [InputRequired()],
        description="Weight this shift to count more or less towards ticket vouchers.",
    )
    notes = TextAreaField(
        "Notes", [Optional()], description="Any notes you want on this template, not visible to attendees."
    )
    delete = BooleanField("Delete")


class RoleForm(Form):
    name = StringField("Role Name", [InputRequired()])
    full_description_md = StringField(
        "Description (supports markdown)",
        [InputRequired()],
        widget=TextArea(),
        description="Displayed in the main role list when signing up.",
    )
    requires_training = BooleanField(
        "Requires training",
        description="Whether volunteers need to complete training before they can sign up for shifts",
    )
    allows_self_training = BooleanField(
        "Allows self training",
        description="If enabled volunteers can declare they've read the training notes and are then considered trained, otherwise they need to be approved by a role admin.",
    )
    uses_bar_training = BooleanField(
        "Uses bar training",
        description="Should only be set for bar roles. Overrides all other training settings. Don't set this unless you know you need it and why.",
    )
    training_notes = StringField(
        "Training notes",
        [Optional()],
        widget=TextArea(),
        description="Details to be shown when a volunteer goes to the training page. If you allow self training a button declaring they've understood will be shown underneath, otherwise they can just read them. (supports markdown)",
    )
    over_18_only = BooleanField(
        "Over 18 only",
        description="Whether we require volunteers to be over 18 for this role. Please use sparingly.",
    )
    role_notes = StringField(
        "Role notes (supports markdown)",
        [Optional()],
        widget=TextArea(),
        description="Displayed to volunteers when they check in for a shift.",
    )
    instructions_url = StringField(
        "Instructions URL",
        [Optional(), URL()],
        description="A link to external instructions. Won't be displayed if role_notes are provided.",
    )
    save = SubmitField("Update")


@volunteer.route("/role-admin", methods=["GET"])
@v_user_required
def role_admin_index():
    if (
        current_user.has_permission("admin")
        or current_user.has_permission("volunteer:manager")
        or current_user.has_permission("volunteer:admin")
    ):
        administered_ids = None
    else:
        administered_ids = current_user.volunteer.administered_role_ids
        if len(administered_ids) == 0:
            flash("You're not an admin for any roles.")
            return redirect(url_for(".choose_role"))

        if len(administered_ids) == 1:
            role_id = next(iter(administered_ids))
            return redirect(url_for(".role_admin", role_id=role_id))

    return render_template(
        "volunteer/role_admin/index.html",
        roles=Role.grouped_by_team(administered_ids),
        volunteer_admin=(
            current_user.has_permission("admin") or current_user.has_permission("volunteer:admin")
        ),
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

    try:
        limit = int(request.args.get("limit", "5"))
        offset = int(request.args.get("offset", "0"))
    except ValueError:
        limit = 5
        offset = 0

    role = get_or_404(db, Role, role_id)
    cutoff = now - timedelta(minutes=30)

    venues = db.session.scalars(
        select(VolunteerVenue)
        .join(Shift, Shift.venue_id == VolunteerVenue.id)
        .where(Shift.role_id == role.id)
        .distinct()
        .order_by(VolunteerVenue.name)
    ).all()
    selected_venue_id = request.args.get("venue_id", 0, type=int)

    shift_query = (
        select(Shift)
        .where(Shift.role_id == role.id and Shift.end >= cutoff)
        .order_by(Shift.end)
        .offset(offset)
        .limit(limit)
    )
    shift_entries_query = select(ShiftEntry).join(ShiftEntry.shift).where(Shift.role_id == role.id)

    if selected_venue_id != 0:
        shift_query = shift_query.where(Shift.venue_id == selected_venue_id)
        shift_entries_query = shift_entries_query.where(Shift.venue_id == selected_venue_id)

    shifts = db.session.scalars(shift_query).all()
    active_shift_entries = db.session.scalars(
        shift_entries_query.where(ShiftEntry.state == ShiftEntryState.ARRIVED)
    ).all()
    pending_shift_entries = db.session.scalars(
        shift_entries_query.where(
            Shift.start <= now - timedelta(minutes=15),
            ShiftEntry.state == ShiftEntryState.SIGNED_UP,
        )
    ).all()

    return render_template(
        "volunteer/role_admin/role.html",
        role=role,
        venues=venues,
        selected_venue_id=selected_venue_id,
        shifts=shifts,
        active_shift_entries=active_shift_entries,
        pending_shift_entries=pending_shift_entries,
        now=now,
        offset=offset,
        limit=limit,
    )


@volunteer.route("role/<int:role_id>/edit", methods=["GET", "POST"])
@role_admin_required
def role_edit(role_id: int) -> ResponseReturnValue:
    """Allows editing details of a role."""
    role = get_or_404(db, Role, role_id)
    form = RoleForm(obj=role)
    if request.method == "POST" and form.validate():
        form.populate_obj(role)
        db.session.add(role)
        db.session.commit()
        flash("Role details have been updated.")
        return redirect(url_for(".role_admin", role_id=role_id))

    return render_template("volunteer/role_admin/edit.html", role=role, form=form)


def _form(template: ShiftTemplate, venue_choices: list[tuple[int, str]]) -> ShiftTemplateForm:
    form = ShiftTemplateForm(obj=template, prefix=f"template-{template.id}")
    form.venue_id.choices = venue_choices
    return form


def _new_form(venue_choices: list[tuple[int, str]], index: int | None = None) -> ShiftTemplateForm:
    prefix = "template-new" if index is None else f"template-new-{index}"
    form = ShiftTemplateForm(prefix=prefix)
    form.venue_id.choices = venue_choices
    return form


def _submitted_new_forms(venue_choices: list[tuple[int, str]]) -> list[ShiftTemplateForm]:
    indices = sorted(
        int(m.group(1)) for key in request.form if (m := re.match(r"^template-new-(\d+)-event_day$", key))
    )
    return [_new_form(venue_choices, i) for i in indices]


def _venue_choices() -> list[tuple[int, str]]:
    return [
        (row.id, row.name)
        for row in db.session.execute(
            select(VolunteerVenue.id, VolunteerVenue.name).order_by(VolunteerVenue.name)
        ).all()
    ]


@volunteer.route("role/<int:role_id>/admin/shift_templates", methods=["GET", "POST"])
@role_admin_required
def role_shift_templates(role_id: int) -> ResponseReturnValue:
    role = get_or_404(db, Role, role_id)
    templates = role.shift_templates
    venue_choices = _venue_choices()

    forms = [_form(template, venue_choices) for template in templates]
    new_forms = _submitted_new_forms(venue_choices) if request.method == "POST" else []
    template_form = _new_form(venue_choices)  # blank form for the <template> element

    if request.method == "POST":
        to_delete = [(f, t) for f, t in zip(forms, templates, strict=True) if f.delete.data]
        to_update = [(f, t) for f, t in zip(forms, templates, strict=True) if not f.delete.data]

        valid = [f.validate() for f, _ in to_update] + [f.validate() for f in new_forms]

        if all(valid):
            for form, template in to_update:
                form.populate_obj(template)
                template.regenerate_shifts()

            for _, template in to_delete:
                db.session.delete(template)

            for new_form in new_forms:
                new_template = ShiftTemplate(role_id=role_id)
                new_form.populate_obj(new_template)
                db.session.add(new_template)
                db.session.flush()  # assign PK before regenerate_shifts uses it
                new_template.regenerate_shifts()

            role.shifts_finalised = "finalise" in request.form
            db.session.commit()

            if role.shifts_finalised:
                flash("Shifts finalised.")
            else:
                flash("Shifts updated.")

            return redirect(url_for(".role_shift_templates", role_id=role_id))

    return render_template(
        "volunteer/role_admin/shift_templates.html",
        role=role,
        forms=forms,
        templates=templates,
        new_forms=new_forms,
        template_form=template_form,
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
    shift.notes = request.form["notes"] if len(request.form["notes"].strip()) > 0 else None
    shift.multiplier = Decimal(request.form["multiplier"])
    db.session.add(shift)
    db.session.commit()

    flash("Shift requirements updated.")
    return redirect(url_for(".role_admin", role_id=role_id, _anchor=f"shift-{shift.id}"))


@volunteer.route("role/<int:role_id>/volunteers")
@role_admin_required
def role_volunteers(role_id):
    role = get_or_404(db, Role, role_id)
    interested = Volunteer.query.join(Volunteer.interested_roles).filter(Role.id == role_id).all()
    entries = ShiftEntry.query.join(ShiftEntry.shift).filter(Shift.role_id == role_id).all()
    signed_up = list(set([se.user.volunteer for se in entries]))
    completed = list(set([se.user.volunteer for se in entries if se.state == "completed"]))
    return render_template(
        "volunteer/role_admin/volunteers.html",
        role=role,
        interested=interested,
        signed_up=signed_up,
        completed=completed,
    )
