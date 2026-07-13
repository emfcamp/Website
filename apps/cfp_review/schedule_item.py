"""
Admin views relating to ScheduleItems and Occurrences
"""

import csv
import json
from datetime import timedelta
from http import HTTPStatus
from io import BytesIO, StringIO

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
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload, undefer
from wtforms import FormField

from apps.cfp.views import TimeRangesHandler
from apps.common import title_add
from apps.config import config
from main import db, get_or_404
from models.content import (
    SCHEDULE_ITEM_INFOS,
    Lottery,
    Occurrence,
    ScheduleItem,
    ScheduleItemPresenter,
    ScheduleItemType,
)
from models.content.attributes import convert_attributes_between_types
from models.user import User

from . import admin_required, bool_qs, cfp_review, sort_schedule_items
from .forms import (
    UPDATE_SCHEDULE_ITEM_ATTRIBUTES_FORM_TYPES,
    AvailabilityOverrideForm,
    CancelOccurrenceForm,
    ChangeScheduleItemOwner,
    ConvertScheduleItemForm,
    CreateOccurrenceForm,
    LotteryForm,
    ScheduleItemForm,
    ScheduleItemPresentersForm,
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
        "proposal_id",
        "type",
        "state",
        "names",
        "pronouns",
        "title",
        "description",
        "short_description",
        "official_content",
        "video_privacy",
        # Attributes
        # "equipment_required",
        # "funding_required",
        "favourite_count",
        "uses_lottery",
    ]

    # Do not call this with untrusted field values
    def get_field(schedule_item, field_path):
        val = schedule_item
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
        download_name=f"schedule_items.{format}",
    )


@cfp_review.route("/occurrences.<format>")
@admin_required
def export_occurrences(format: str) -> ResponseReturnValue:
    fields = [
        "id",
        "schedule_item.id",
        "occurrence_num",
        "schedule_item.proposal_id",
        "schedule_item.type",
        "schedule_item.state",
        "schedule_item.names",
        "schedule_item.pronouns",
        "schedule_item.title",
        "schedule_item.description",
        "schedule_item.short_description",
        "schedule_item.official_content",
        "schedule_item.contact_telephone",
        "cancelled",
        "scheduled_time",
        "scheduled_venue_id",
        "video_privacy",
        "c3voc_url",
        "youtube_url",
        "thumbnail_url",
        "video_recording_lost",
        "uses_lottery",
    ]

    # Do not call this with untrusted field values
    def get_field(occurrence, field_path):
        val = occurrence
        for field in field_path.split("."):
            val = getattr(val, field)
        return val

    # There's no separate "occurrences list" page
    schedule_items, _ = filter_schedule_item_request()
    occurrences = [o for s in schedule_items for o in s.occurrences]
    if format == "csv":
        mime = "text/csv"
        buf = StringIO()
        w = csv.writer(buf)
        # Header row
        w.writerow(fields)
        for o in occurrences:
            cells = []
            for field in fields:
                cell = get_field(o, field)
                cells.append(cell)
            w.writerow(cells)
        out = buf.getvalue()
    elif format == "json":
        mime = "application/json"
        out = json.dumps(
            [{a: get_field(o, a) for a in fields} for o in occurrences],
            default=str,
        )
    else:
        abort(HTTPStatus.BAD_REQUEST, "Unsupported export format")
    return send_file(
        BytesIO(out.encode()),
        mime,
        as_attachment=True,
        download_name=f"occurrences.{format}",
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
        # wtforms is ridiculous
        form.official_content.data = schedule_item.official_content

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

    form = UpdateAvailabilityForm(obj=schedule_item)
    time_ranges = TimeRangesHandler(schedule_item)

    if form.validate_on_submit() and time_ranges.validate():
        availability_changed = time_ranges.save()

        overrides = sorted(
            (entry.start.data, entry.end.data)
            for entry in form.availability_overrides
            if entry.start.data and entry.end.data
        )
        overrides_changed = overrides != schedule_item.availability_overrides
        if overrides_changed:
            schedule_item.availability_overrides = overrides

        has_been_through_scheduler = any(
            o.potential_time or o.scheduled_time for o in schedule_item.occurrences
        )
        if (availability_changed or overrides_changed) and has_been_through_scheduler:
            flash("You need to run the scheduler again to take account of availability changes")

        db.session.commit()

        return redirect(url_for(".schedule_item_availability", schedule_item_id=schedule_item_id))

    override_template = AvailabilityOverrideForm(prefix="availability_overrides-__index__-")

    time_range_kw = {
        "min": config.event_start.strftime("%Y-%m-%dT%H:%M"),
        # Late-night time blocks can run past EVENT_END - see AvailabilityOverrideForm.validate_end
        "max": ((config.event_end + timedelta(days=1)).replace(hour=2, minute=0)).strftime("%Y-%m-%dT%H:%M"),
        "step": 600,
    }
    for entry in [*form.availability_overrides, override_template]:
        entry.start.render_kw = time_range_kw
        entry.end.render_kw = time_range_kw

    return render_template(
        "cfp_review/schedule_item/availability.html",
        schedule_item=schedule_item,
        form=form,
        time_ranges=time_ranges,
        override_template=override_template,
    )


@cfp_review.route("/schedule-items/<int:schedule_item_id>/convert", methods=["GET", "POST"])
@admin_required
def convert_schedule_item(schedule_item_id: int) -> ResponseReturnValue:
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)

    form = ConvertScheduleItemForm()
    form.new_type.choices = [
        (ti.type, title_add(ti.human_type))
        for ti in SCHEDULE_ITEM_INFOS.values()
        if ti.type != schedule_item.type
    ]

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


@cfp_review.route("/schedule-items/<int:schedule_item_id>/presenters", methods=["GET", "POST"])
@admin_required
def schedule_item_presenters(schedule_item_id: int) -> ResponseReturnValue:
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)

    form = ScheduleItemPresentersForm()

    if form.validate_on_submit():
        user = db.session.get(User, form.user_id.data)
        if not user:
            abort(400)

        if form.delete.data:
            if schedule_item not in user.presented_schedule_items:
                flash("The user was already not presenting this schedule item")
                return redirect(url_for(".schedule_item_presenters", schedule_item_id=schedule_item_id))

            for sip in schedule_item.schedule_item_presenters:
                if sip.user == user:
                    flash("Presenter removed")
                    db.session.delete(sip)

        elif form.add.data:
            if schedule_item in user.presented_schedule_items:
                flash("This user is already presenting this schedule item")
                return redirect(url_for(".schedule_item_presenters", schedule_item_id=schedule_item_id))

            flash("Presenter added")
            db.session.add(
                ScheduleItemPresenter(
                    schedule_item=schedule_item,
                    user=user,
                )
            )

        db.session.commit()
        return redirect(url_for(".schedule_item_presenters", schedule_item_id=schedule_item_id))

    try:
        size = int(request.args.get("size", 500))
    except ValueError:
        return redirect(url_for(".users"))

    search = request.args.get("search")
    if search is not None:
        query = db.select(User).where(or_(User.name.ilike(f"%{search}%"), User.email.ilike(f"%{search}%")))
        users = query.order_by(User.id)
        total_users = db.session.query(func.count(User.id)).scalar()
        users_paged = db.paginate(users, per_page=size, error_out=False)
    else:
        users = None
        total_users = None
        users_paged = None

    return render_template(
        "cfp_review/schedule_item/presenters.html",
        schedule_item=schedule_item,
        form=form,
        search=search,
        users=users_paged,
        total_users=total_users,
    )


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
    occurrence: Occurrence = get_or_404(db, Occurrence, occurrence_id)
    if occurrence.schedule_item_id != schedule_item_id:
        return redirect(
            url_for(
                ".update_occurrence",
                schedule_item_id=occurrence.schedule_item_id,
                occurrence_id=occurrence.id,
            )
        )

    Form = get_update_occurrence_type_form(occurrence.schedule_item.type)
    form = Form(obj=occurrence)

    form.scheduled_time.render_kw = {
        "min": config.event_start.strftime("%Y-%m-%dT%H:%M"),
        "max": config.event_end.strftime("%Y-%m-%dT%H:%M"),
        "step": 600,
    }

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
            # These can get replaced with del as soon as we include https://github.com/pallets-eco/wtforms/pull/923 (wtforms 3.3)
            form.lottery.state.choices = [(c, _) for c, _ in form.lottery.state.choices if c == "completed"]
        else:
            form.lottery.state.choices = [(c, _) for c, _ in form.lottery.state.choices if c != "completed"]
    elif hasattr(form, "lottery"):
        form.lottery.state.choices.insert(0, ("", ""))
        form.lottery.state.choices = [(c, _) for c, _ in form.lottery.state.choices if c != "completed"]

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
        elif hasattr(form, "lottery") and not occurrence.lottery:
            del form.lottery

        form.populate_obj(occurrence)

        assert form.allowed_venue_ids.data is not None
        occurrence.allowed_venues = [venues_dict[v] for v in form.allowed_venue_ids.data]

        if (
            occurrence.manually_scheduled
            and occurrence.scheduled_time is not None
            and occurrence.scheduled_duration is not None
            and not occurrence.allowed_times(True)
        ):
            flash(
                f"ERROR: Manually scheduled time outside any '{occurrence.schedule_item.human_type}' Time Blocks in the allowed venues"
            )
            db.session.rollback()
        else:
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
