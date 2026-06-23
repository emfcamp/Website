"""
Admin views relating to ScheduleItems and Occurrences
"""

import csv
import json
from http import HTTPStatus
from io import BytesIO, StringIO
from typing import get_args

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask import current_app as app
from flask.typing import ResponseReturnValue
from flask_login import current_user
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload, undefer
from wtforms import FormField

from apps.cfp.views import TimeRangesHandler
from main import db, get_or_404
from models.content import (
    SCHEDULE_ITEM_INFOS,
    Lottery,
    Occurrence,
    ScheduleItem,
    ScheduleItemType,
)
from models.content.attributes import convert_attributes_between_types
from models.user import User

from . import admin_required, bool_qs, cfp_review, sort_schedule_items
from .forms import (
    UPDATE_SCHEDULE_ITEM_ATTRIBUTES_FORM_TYPES,
    CancelOccurrenceForm,
    ChangeScheduleItemOwner,
    ConvertScheduleItemForm,
    CreateOccurrenceForm,
    LotteryForm,
    ScheduleItemForm,
    UpdateAvailabilityForm,
    UpdateOccurrenceForm,
    UpdateScheduleItemForm,
)


def filter_schedule_item_request() -> tuple[list[ScheduleItem], bool]:
    schedule_item_query = select(ScheduleItem)
    is_filtered = False

    bool_names: list[str] = []
    bool_vals = [request.args.get(n, type=bool_qs) for n in bool_names]
    bool_dict = {n: v for n, v in zip(bool_names, bool_vals, strict=True) if v is not None}
    if bool_dict:
        is_filtered = True
        schedule_item_query = schedule_item_query.filter_by(**bool_dict)

    types = request.args.getlist("type")
    if types:
        is_filtered = True
        schedule_item_query = schedule_item_query.where(ScheduleItem.type.in_(types))

    states = request.args.getlist("state")
    if states:
        is_filtered = True
        schedule_item_query = schedule_item_query.where(ScheduleItem.state.in_(states))

    official_content = sorted(request.args.getlist("official_content"))
    if official_content == ["attendee"] or official_content == ["official"]:
        is_filtered = True
        official_content_bool = official_content == ["official"]
        schedule_item_query = schedule_item_query.where(
            ScheduleItem.official_content == official_content_bool
        )

    no_occurrence = request.args.get("no_occurrence", type=bool_qs)
    if no_occurrence:
        is_filtered = True
        schedule_item_query = schedule_item_query.filter(~ScheduleItem.occurrences.any())

    no_duration = request.args.get("no_duration", type=bool_qs)
    if no_duration:
        is_filtered = True
        schedule_item_query = schedule_item_query.join(ScheduleItem.occurrences).filter(
            Occurrence.scheduled_duration.is_(None)
        )

    schedule_item_query = (
        schedule_item_query.group_by(ScheduleItem.id)
        .options(selectinload(ScheduleItem.occurrences))
        .options(undefer(ScheduleItem.favourite_count))
    )
    schedule_items = list(db.session.scalars(schedule_item_query))

    sort_schedule_items(schedule_items)

    return schedule_items, is_filtered


@cfp_review.route("/schedule-items")
@admin_required
def schedule_items() -> ResponseReturnValue:
    schedule_items, is_filtered = filter_schedule_item_request()
    non_sort_query_string: dict[str, list[str]] = request.args.to_dict(flat=False)

    non_sort_query_string.pop("sort_by", None)
    non_sort_query_string.pop("reverse", None)

    return render_template(
        "cfp_review/schedule_item/schedule_items.html",
        schedule_items=schedule_items,
        new_qs=non_sort_query_string,
        is_filtered=is_filtered,
        total_schedule_items=db.session.scalar(select(func.count(ScheduleItem.id))),
    )


@cfp_review.route("/schedule-items.<format>")
@admin_required
def export_schedule_items(format: str) -> ResponseReturnValue:
    fields = [
        "id",
        "state",
        "names",
        "pronouns",
        "type",
        "title",
        "description",
        "short_description",
        "duration",
        "arrival_period",
        "departure_period",
        "available_times",
        "contact_telephone",
        "contact_eventphone",
        "official_content",
        "equipment_required",
        "funding_required",
        "notice_required",
        "additional_info",
        # FIXME: do we need any of these?
        # "tags",
        # "favourite_count",
    ]

    # Do not call this with untrusted field values
    def get_field(proposal, field_path):
        val = proposal
        for field in field_path.split("."):
            val = getattr(val, field)
        return val

    schedule_items, _ = filter_schedule_item_request()
    if format == "csv":
        mime = "text/csv"
        buf = StringIO()
        w = csv.writer(buf)
        # Header row
        w.writerow(fields)
        for s in schedule_items:
            cells = []
            for field in fields:
                cell = get_field(s, field)
                cells.append(cell)
            w.writerow(cells)
        out = buf.getvalue()
    elif format == "json":
        mime = "application/json"
        out = json.dumps(
            [{a: get_field(s, a) for a in fields} for s in schedule_items],
            default=str,
        )
    else:
        abort(HTTPStatus.BAD_REQUEST, "Unsupported export format")
    return send_file(
        BytesIO(out.encode()),
        mime,
        as_attachment=True,
        download_name=f"proposals.{format}",
    )


@cfp_review.route("/schedule-items/<int:schedule_item_id>")
@admin_required
def schedule_item(schedule_item_id: int) -> ResponseReturnValue:
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)

    return render_template("cfp_review/schedule_item/schedule_item.html", schedule_item=schedule_item)


@cfp_review.route("/schedule-items/<int:schedule_item_id>/edit", methods=["GET", "POST"])
@admin_required
def update_schedule_item(schedule_item_id: int) -> ResponseReturnValue:
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)

    Form = get_update_schedule_item_type_form(schedule_item.type)
    form = Form(obj=schedule_item)

    if form.validate_on_submit():
        form.populate_obj(schedule_item)

        if form.update.data:
            msg = f"Updating schedule item {schedule_item_id}"
            flash(msg)
            app.logger.info(msg)
            db.session.commit()

        return redirect(url_for(".update_schedule_item", schedule_item_id=schedule_item_id))

    if request.method != "POST":
        form.official_content.data = (schedule_item.official_content and "official") or "attendee"

    occurrence_form = CreateOccurrenceForm()

    return render_template(
        "cfp_review/schedule_item/schedule_item_edit.html",
        schedule_item=schedule_item,
        form=form,
        occurrence_form=occurrence_form,
    )


@cfp_review.route("/schedule-items/<int:schedule_item_id>/availability", methods=["GET", "POST"])
@admin_required
def schedule_item_availability(schedule_item_id: int) -> ResponseReturnValue:
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)

    form = UpdateAvailabilityForm()
    time_ranges = TimeRangesHandler(schedule_item)

    if form.validate_on_submit() and time_ranges.validate():
        availability_changed = time_ranges.save()
        has_been_through_scheduler = any(
            o.potential_time or o.scheduled_time for o in schedule_item.occurrences
        )
        if availability_changed and has_been_through_scheduler:
            flash("You need to run the scheduler again to take account of availability changes")

        db.session.commit()

        return redirect(url_for(".schedule_item_availability", schedule_item_id=schedule_item_id))

    return render_template(
        "cfp_review/schedule_item/availability.html",
        schedule_item=schedule_item,
        form=form,
        time_ranges=time_ranges,
    )


@cfp_review.route("/schedule-items/<int:schedule_item_id>/convert", methods=["GET", "POST"])
@admin_required
def convert_schedule_item(schedule_item_id: int) -> ResponseReturnValue:
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)

    form = ConvertScheduleItemForm()
    types = get_args(ScheduleItemType)
    form.new_type.choices = [(t, t.title()) for t in types if t != schedule_item.type]

    if form.validate_on_submit():
        new_type = form.new_type.data
        _convert_schedule_item(schedule_item, new_type)

        db.session.commit()

        return redirect(url_for(".update_schedule_item", schedule_item_id=schedule_item.id))

    return render_template(
        "cfp_review/schedule_item/convert_schedule_item.html", schedule_item=schedule_item, form=form
    )


def _convert_schedule_item(schedule_item: ScheduleItem, new_type: ScheduleItemType) -> None:
    # This can also be called by attendee content managers
    for occurrence in schedule_item.occurrences:
        # Fall back to the defaults, as we don't know why this was set
        occurrence.allowed_venues = []

    old_attributes = schedule_item.attributes
    schedule_item.type = new_type  # affects type_info
    new_attributes = schedule_item.type_info.attributes_cls()
    convert_attributes_between_types(old_attributes, new_attributes)
    schedule_item.attributes = new_attributes


@cfp_review.route("/schedule-items/<int:schedule_item_id>/occurrences", methods=["POST"])
@admin_required
def occurrences(schedule_item_id: int) -> ResponseReturnValue:
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)

    form = CreateOccurrenceForm()
    if form.validate_on_submit():
        occurrence_num = 1
        for occurrence in schedule_item.occurrences:
            if occurrence.occurrence_num == occurrence_num:
                occurrence_num += 1
            else:
                break
        occurrence = Occurrence(
            schedule_item=schedule_item,
            occurrence_num=occurrence_num,
        )
        schedule_item.occurrences.append(occurrence)
        db.session.add(occurrence)
        db.session.commit()
        return redirect(
            url_for(".update_occurrence", schedule_item_id=schedule_item.id, occurrence_id=occurrence.id)
        )

    return redirect(url_for(".update_schedule_item", schedule_item_id=schedule_item.id))


@cfp_review.route(
    "/schedule-items/<int:schedule_item_id>/occurrences/<int:occurrence_id>", methods=["GET", "POST"]
)
@admin_required
def update_occurrence(schedule_item_id: int, occurrence_id: int) -> ResponseReturnValue:
    occurrence: Occurrence | None = db.session.scalar(
        select(Occurrence)
        .filter_by(id=occurrence_id, schedule_item_id=schedule_item_id)
        .options(selectinload(Occurrence.schedule_item))
    )
    if not occurrence:
        abort(404)

    Form = get_update_occurrence_type_form(occurrence.schedule_item.type)
    form = Form(obj=occurrence)

    valid_allowed_venues = set(occurrence.valid_allowed_venues)
    # We don't block saving an occurrence if the valid list has changed
    # allowed_venues is an input into the scheduler, not a constraint on us
    valid_allowed_venues |= set(occurrence.get_allowed_venues())
    if occurrence.scheduled_venue:
        valid_allowed_venues.add(occurrence.scheduled_venue)

    venues_dict = {v.id: v for v in valid_allowed_venues}
    allowed_venue_choices = [
        (str(v.id), v.name) for v in sorted(valid_allowed_venues, key=lambda v: v.priority, reverse=True)
    ]
    form.allowed_venue_ids.choices = allowed_venue_choices

    form.scheduled_venue_id.choices = [("", "")] + allowed_venue_choices

    if occurrence.lottery:
        if occurrence.lottery.state == "completed":
            form.lottery.state.choices = [(c, _) for c, _ in form.lottery.state.choices if c == "completed"]
        else:
            form.lottery.state.choices = [(c, _) for c, _ in form.lottery.state.choices if c != "completed"]
    elif hasattr(form, "lottery"):
        form.lottery.state.choices.insert(0, ("", ""))

    if form.validate_on_submit():
        if (
            occurrence.schedule_item.type_info.supports_lottery
            and not occurrence.lottery
            and form.lottery.state.data != ""
        ):
            occurrence.lottery = Lottery(
                occurrence=occurrence,
            )
            db.session.add(occurrence.lottery)
        elif hasattr(form, "lottery"):
            del form.lottery

        form.populate_obj(occurrence)

        assert form.allowed_venue_ids.data is not None
        occurrence.allowed_venues = [venues_dict[v] for v in form.allowed_venue_ids.data]
        db.session.commit()
        return redirect(
            url_for(".update_occurrence", schedule_item_id=schedule_item_id, occurrence_id=occurrence_id)
        )

    if request.method != "POST":
        form.allowed_venue_ids.data = [v.id for v in occurrence.get_allowed_venues()]

        if occurrence.schedule_item.type_info.supports_lottery:
            form.lottery.max_tickets_per_entry.default = (
                occurrence.schedule_item.type_info.default_max_tickets_per_entry
            )

        if not occurrence.lottery and hasattr(form, "lottery"):
            form.lottery.state.data = ""

    cancel_form = CancelOccurrenceForm()

    return render_template(
        "cfp_review/schedule_item/occurrence.html",
        schedule_item=occurrence.schedule_item,
        occurrence=occurrence,
        form=form,
        cancel_form=cancel_form,
    )


@cfp_review.route(
    "/schedule-items/<int:schedule_item_id>/occurrences/<int:occurrence_id>/cancel", methods=["POST"]
)
@admin_required
def cancel_occurrence(schedule_item_id: int, occurrence_id: int) -> ResponseReturnValue:
    occurrence: Occurrence = get_or_404(db, Occurrence, occurrence_id)
    if occurrence.schedule_item_id != schedule_item_id:
        abort(404)

    cancel_form = CancelOccurrenceForm()
    if occurrence.cancelled:
        del cancel_form.cancel
    else:
        del cancel_form.uncancel

    if not cancel_form.validate_on_submit():
        abort(400)

    if occurrence.cancelled:
        occurrence.uncancel()
    else:
        occurrence.cancel()
    db.session.commit()
    return redirect(
        url_for(".update_occurrence", schedule_item_id=schedule_item_id, occurrence_id=occurrence_id)
    )


@cfp_review.route("/schedule-items/<int:schedule_item_id>/change-owner", methods=["GET", "POST"])
@admin_required
def schedule_item_change_owner(schedule_item_id: int) -> ResponseReturnValue:
    form = ChangeScheduleItemOwner()
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)

    if form.validate_on_submit() and form.submit.data:
        assert form.user_email.data  # DataRequired

        user = form._user
        if not user:
            assert form.user_name.data  # validate_user_name
            user = User(form.user_email.data, form.user_name.data)
            db.session.add(user)

            msg = f"Created new user {user.email}"
            app.logger.info(msg)
            flash(msg)

        schedule_item.user = user
        db.session.commit()

        msg = f"Transferred ownership of schedule item {schedule_item.id} to {user.name}"
        app.logger.info(msg)
        flash(msg)

        return redirect(url_for(".update_schedule_item", schedule_item_id=schedule_item_id))

    return render_template(
        "cfp_review/schedule_item/change_schedule_item_owner.html",
        form=form,
        schedule_item=schedule_item,
    )


def get_update_schedule_item_type_form(schedule_item_type: ScheduleItemType) -> type[UpdateScheduleItemForm]:
    class UpdateScheduleItemFormWithAttributes(UpdateScheduleItemForm):
        pass

    UpdateScheduleItemFormWithAttributes.attributes = FormField(
        UPDATE_SCHEDULE_ITEM_ATTRIBUTES_FORM_TYPES[schedule_item_type]
    )

    return UpdateScheduleItemFormWithAttributes


def get_update_occurrence_type_form(schedule_item_type: ScheduleItemType) -> type[UpdateOccurrenceForm]:
    type_info = SCHEDULE_ITEM_INFOS[schedule_item_type]
    if not type_info.supports_lottery:
        return UpdateOccurrenceForm

    class UpdateOccurrenceFormWithLottery(UpdateOccurrenceForm):
        pass

    UpdateOccurrenceFormWithLottery.lottery = FormField(LotteryForm)

    return UpdateOccurrenceFormWithLottery


@cfp_review.route("/schedule-items/new", methods=["GET"])
@admin_required
def schedule_item_create() -> ResponseReturnValue:
    """Create a schedule item. This is used for items scheduled directly by the content team, such as films and music."""

    return render_template("cfp_review/schedule_item/create_select.html")


@cfp_review.route("/schedule-items/new/<string:type>", methods=["GET", "POST"])
@admin_required
def schedule_item_create_type(type: ScheduleItemType) -> ResponseReturnValue:
    """Create a schedule item. This is used for items scheduled directly by the content team, such as films and music."""

    AttributesForm = UPDATE_SCHEDULE_ITEM_ATTRIBUTES_FORM_TYPES[type]

    class CreateForm(ScheduleItemForm):
        attributes = FormField(AttributesForm)

    form = CreateForm()

    if form.validate_on_submit():
        si = ScheduleItem(type=type, user=current_user)
        form.populate_obj(si)
        si.occurrences = [Occurrence(occurrence_num=1)]
        db.session.add(si)

        db.session.commit()

        return redirect(url_for(".schedule_item", schedule_item_id=si.id))

    return render_template(
        "cfp_review/schedule_item/create.html",
        form=form,
        type=SCHEDULE_ITEM_INFOS[type],
    )
