"""
Admin views relating to ScheduleItems and Occurrences
"""

import csv
import json
from collections import Counter
from http import HTTPStatus
from io import BytesIO, StringIO
from typing import Any, get_args

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
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload, undefer
from wtforms import FormField

from apps.cfp_review.estimation import get_cfp_estimate
from main import db, get_or_404
from models.content import (
    SCHEDULE_ITEM_INFOS,
    Lottery,
    Occurrence,
    ScheduleItem,
    ScheduleItemState,
    ScheduleItemType,
)
from models.content.attributes import convert_attributes_between_types
from models.user import User

from . import admin_required, bool_qs, cfp_review, schedule_required, sort_schedule_items
from .forms import (
    UPDATE_SCHEDULE_ITEM_ATTRIBUTES_FORM_TYPES,
    ChangeScheduleItemOwner,
    ConvertScheduleItemForm,
    CreateOccurrenceForm,
    LotteryForm,
    UpdateOccurrenceForm,
    UpdateScheduleItemForm,
)


@cfp_review.route("/schedule-items")
@admin_required
def schedule_items() -> ResponseReturnValue:
    schedule_items, is_filtered = filter_schedule_item_request()
    non_sort_query_string: dict[str, list[str]] = request.args.to_dict(flat=False)

    non_sort_query_string.pop("sort_by", None)
    non_sort_query_string.pop("reverse", None)

    return render_template(
        "cfp_review/schedule/schedule_items.html",
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


@cfp_review.route("/schedule-items/<int:schedule_item_id>", methods=["GET", "POST"])
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
        "cfp_review/schedule/schedule_item.html",
        schedule_item=schedule_item,
        form=form,
        occurrence_form=occurrence_form,
    )


@cfp_review.route("/schedule-items-summary")
@schedule_required
def schedule_items_summary() -> ResponseReturnValue:
    counts_by_state: dict[ScheduleItemState, Counter[Any]] = {
        s: Counter() for s in get_args(ScheduleItemState)
    }
    counts_by_type: Counter[ScheduleItemType] = Counter()

    for schedule_item in db.session.query(ScheduleItem).filter(ScheduleItem.official_content).all():
        counts_by_type[schedule_item.type] += 1
        counts_by_state[schedule_item.state]["total"] += 1
        counts_by_state[schedule_item.state][schedule_item.type] += 1

    schedule_item_types: list[ScheduleItemType] = ["talk", "workshop", "performance", "film"]

    estimates = {
        schedule_item_type: get_cfp_estimate(schedule_item_type) for schedule_item_type in schedule_item_types
    }
    return render_template(
        "cfp_review/schedule/schedule_items_summary.html",
        counts_by_type=counts_by_type,
        counts_by_state=counts_by_state,
        estimates=estimates,
    )


@cfp_review.route("/schedule-items/<int:schedule_item_id>/convert", methods=["GET", "POST"])
@admin_required
def convert_schedule_item(schedule_item_id: int) -> ResponseReturnValue:
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)

    if schedule_item.proposal:
        # We don't want to get into having mismatched proposal/schedule_item types yet
        flash("The schedule item is associated with a proposal, please convert this instead.")
        return redirect(url_for(".convert_proposal", proposal_id=schedule_item.proposal_id))

    form = ConvertScheduleItemForm()
    types = get_args(ScheduleItemType)
    form.new_type.choices = [(t, t.title()) for t in types if t != schedule_item.type]

    if form.validate_on_submit():
        new_type = form.new_type.data
        _convert_schedule_item(schedule_item, new_type)

        db.session.commit()

        return redirect(url_for(".update_schedule_item", schedule_item_id=schedule_item.id))

    return render_template(
        "cfp_review/schedule/convert_schedule_item.html", schedule_item=schedule_item, form=form
    )


def _convert_schedule_item(schedule_item: ScheduleItem, new_type: ScheduleItemType) -> None:
    # This can also be called by attendee content managers

    # People's availability can vary based on type
    schedule_item.available_times = None

    for occurrence in schedule_item.occurrences:
        # Fall back to the defaults, as we don't know why this was set
        occurrence.allowed_venues = []

    old_attributes = schedule_item.attributes
    schedule_item.type = new_type  # affects type_info
    new_attributes = schedule_item.type_info.attributes_cls()
    convert_attributes_between_types(old_attributes, new_attributes)
    schedule_item.attributes = new_attributes


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

    schedule_item_query = schedule_item_query.options(selectinload(ScheduleItem.occurrences)).options(
        undefer(ScheduleItem.favourite_count)
    )
    schedule_items = list(db.session.scalars(schedule_item_query))

    sort_schedule_items(schedule_items)

    return schedule_items, is_filtered


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
            state="unscheduled",
            video_privacy=schedule_item.default_video_privacy,
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
    valid_allowed_venues |= set(occurrence.allowed_venues)
    if occurrence.potential_venue:
        valid_allowed_venues.add(occurrence.potential_venue)
    if occurrence.scheduled_venue:
        valid_allowed_venues.add(occurrence.scheduled_venue)

    venues_dict = {v.id: v for v in valid_allowed_venues}
    allowed_venue_choices = [
        (str(v.id), v.name) for v in sorted(valid_allowed_venues, key=lambda v: v.priority, reverse=True)
    ]
    form.allowed_venue_ids.choices = allowed_venue_choices
    form.scheduled_venue_id.choices = [("", "")] + allowed_venue_choices
    form.potential_venue_id.choices = [("", "")] + allowed_venue_choices

    if form.validate_on_submit():
        if occurrence.schedule_item.type_info.supports_lottery and not occurrence.lottery:
            occurrence.lottery = Lottery(
                occurrence=occurrence,
            )
            db.session.add(occurrence.lottery)

        form.populate_obj(occurrence)

        # FIXME: this is horrible
        allowed_times = form.allowed_times_str.data
        assert allowed_times is not None
        # Apparently this was required for Windows (presumably IE) users
        # Let's see if it still happens
        if "\r" in allowed_times:
            app.logger.warning("Fixing up newlines")
            allowed_times = allowed_times.replace("\r\n", "\n")
        allowed_times = allowed_times.strip()
        if occurrence.get_allowed_time_periods_serialised().strip() != allowed_times:
            occurrence.allowed_times = allowed_times or None

        assert form.allowed_venue_ids.data is not None
        occurrence.allowed_venues = [venues_dict[v] for v in form.allowed_venue_ids.data]

        db.session.commit()
        return redirect(
            url_for(".update_occurrence", schedule_item_id=schedule_item_id, occurrence_id=occurrence_id)
        )

    if request.method != "POST":
        form.allowed_times_str.data = occurrence.allowed_times or ""
        form.allowed_venue_ids.data = [v.id for v in occurrence.valid_allowed_venues]

        if occurrence.schedule_item.type_info.supports_lottery:
            form.lottery.max_tickets_per_entry.default = (
                occurrence.schedule_item.type_info.default_max_tickets_per_entry
            )

    return render_template(
        "cfp_review/schedule/occurrence.html",
        schedule_item=occurrence.schedule_item,
        occurrence=occurrence,
        form=form,
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
        "cfp_review/schedule/change_schedule_item_owner.html",
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
