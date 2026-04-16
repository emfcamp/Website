import csv
import json
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import timedelta
from http import HTTPStatus
from io import BytesIO, StringIO
from itertools import combinations
from typing import Any, Literal, get_args

import dateutil
from flask import (
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask import (
    current_app as app,
)
from flask.typing import ResponseReturnValue
from flask_login import current_user
from flask_mailman import EmailMessage
from sqlalchemy import and_, func, select
from sqlalchemy.orm import joinedload, selectinload, undefer
from sqlalchemy_continuum.utils import version_class
from wtforms import FormField

from apps.common import get_next_url
from main import db, external_url, get_or_404
from models.content import (
    SCHEDULE_ITEM_INFOS,
    Lottery,
    Occurrence,
    Proposal,
    ProposalMessage,
    ProposalState,
    ProposalTag,
    ProposalType,
    ProposalVote,
    ScheduleItem,
    ScheduleItemState,
    ScheduleItemType,
    Tag,
    Venue,
)
from models.content.attributes import convert_attributes_between_types
from models.permission import Permission
from models.purchase import AdmissionTicket
from models.user import User

from ..common.email import from_email
from . import (
    admin_required,
    cfp_review,
    get_next_proposal_to,
    schedule_required,
    sort_proposals,
    sort_schedule_items,
)
from .estimation import get_cfp_estimate
from .forms import (
    UPDATE_PROPOSAL_ATTRIBUTES_FORM_TYPES,
    UPDATE_SCHEDULE_ITEM_ATTRIBUTES_FORM_TYPES,
    AcceptanceForm,
    ChangeProposalOwner,
    ChangeScheduleItemOwner,
    CloseRoundForm,
    ConvertProposalForm,
    ConvertScheduleItemForm,
    CreateOccurrenceForm,
    InviteSpeakerForm,
    LotteryForm,
    PrivateNotesForm,
    ReversionForm,
    SendMessageForm,
    UpdateOccurrenceForm,
    UpdateProposalForm,
    UpdateScheduleItemForm,
    UpdateVotesForm,
)
from .majority_judgement import calculate_max_normalised_score


@cfp_review.route("/")
def main() -> ResponseReturnValue:
    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".main")))

    if current_user.has_permission("cfp_admin"):
        return redirect(url_for(".proposals"))

    if current_user.has_permission("cfp_anonymiser"):
        return redirect(url_for(".anonymisation"))

    if current_user.has_permission("cfp_reviewer"):
        return redirect(url_for(".review_list"))

    abort(404)


@cfp_review.route("help")
def help():
    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".main")))
    return render_template("cfp_review/help.html")


def bool_qs(val):
    # Explicit true/false values are better than the implicit notset=&set=anything that bool does
    if val in ["True", "1"]:
        return True
    if val in ["False", "0"]:
        return False
    raise ValueError("Invalid querystring boolean")


def filter_proposal_request() -> tuple[list[Proposal], bool]:
    proposal_query = select(Proposal)
    is_filtered = False

    bool_names: list[str] = ["one_day", "needs_help", "needs_money"]
    bool_vals = [request.args.get(n, type=bool_qs) for n in bool_names]
    bool_dict = {n: v for n, v in zip(bool_names, bool_vals, strict=True) if v is not None}
    if bool_dict:
        is_filtered = True
        proposal_query = proposal_query.filter_by(**bool_dict)

    types = request.args.getlist("type")
    if types:
        is_filtered = True
        proposal_query = proposal_query.where(Proposal.type.in_(types))

    states = request.args.getlist("state")
    if states:
        is_filtered = True
        proposal_query = proposal_query.where(Proposal.state.in_(states))

    needs_ticket = request.args.get("needs_ticket", type=bool_qs)
    if needs_ticket is True:
        is_filtered = True
        proposal_query = proposal_query.where(
            ~Proposal.user.has(User.will_have_ticket.is_(True)),
            ~Proposal.user.has(
                User.owned_admission_tickets.any(AdmissionTicket.state.in_(["paid", "payment-pending"]))
            ),
        )

    tags = request.args.getlist("tags")
    if "untagged" in tags:
        if len(tags) > 1:
            flash("'untagged' in 'tags' arg, other tags ignored")
        is_filtered = True
        proposal_query = proposal_query.where(~Proposal._tags.any())

    elif tags:
        is_filtered = True
        proposal_query = proposal_query.where(Proposal._tags.any(Tag.tag.in_(tags)))

    proposal_query = proposal_query.options(
        selectinload(Proposal.user).selectinload(User.owned_tickets)
    ).options(selectinload(Proposal._tags))
    proposals = list(db.session.scalars(proposal_query))

    sort_proposals(proposals)

    return proposals, is_filtered


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


@cfp_review.route("/proposals")
@admin_required
def proposals() -> ResponseReturnValue:
    proposals, is_filtered = filter_proposal_request()
    non_sort_query_string = request.args.to_dict(flat=False)

    non_sort_query_string.pop("sort_by", None)
    non_sort_query_string.pop("reverse", None)

    tag_counts = dict(
        db.session.query(Tag.tag, db.func.count(ProposalTag.c.proposal_id))
        .select_from(Tag)
        .outerjoin(ProposalTag)
        .group_by(Tag.tag)
        .order_by(Tag.tag)
        .all()
    )
    tag_counts = {tag: [0, total_count] for tag, total_count in tag_counts.items()}
    for proposal in proposals:
        for tag in proposal.tags:
            tag_counts[tag][0] += 1

    return render_template(
        "cfp_review/proposals.html",
        proposals=proposals,
        new_qs=non_sort_query_string,
        is_filtered=is_filtered,
        total_proposals=db.session.scalar(select(func.count(Proposal.id))),
        tag_counts=tag_counts,
    )


@cfp_review.route("/schedule-items")
@admin_required
def schedule_items() -> ResponseReturnValue:
    schedule_items, is_filtered = filter_schedule_item_request()
    non_sort_query_string: dict[str, list[str]] = request.args.to_dict(flat=False)

    non_sort_query_string.pop("sort_by", None)
    non_sort_query_string.pop("reverse", None)

    return render_template(
        "cfp_review/schedule_items.html",
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


ProposalEmailReason = Literal[
    "accepted",
    "still-considered",
    "rejected",
    "check-scheduled-duration",
    "please-finalise",
    "reserve-list",
    "slot-scheduled",
    "slot-moved",
]


def send_email_for_proposal(proposal: Proposal, reason: ProposalEmailReason) -> None:
    from_email_ = from_email("CONTENT_EMAIL")
    title = (proposal.schedule_item and proposal.schedule_item.title) or proposal.title

    if reason == "accepted":
        subject = f'''Your EMF {proposal.human_type} "{title}" has been accepted!'''
        template = "cfp_review/email/accepted_msg.txt"

    elif reason == "still-considered":
        subject = f'''We're still considering your EMF {proposal.human_type} "{title}"'''
        template = "cfp_review/email/not_accepted_msg.txt"

    elif reason == "rejected":
        # remember to set rejected_email_sent
        subject = f'''Your EMF {proposal.human_type} "{title}" was not accepted.'''
        template = "emails/cfp-rejected.txt"

    elif reason == "reserve-list":
        subject = f'''Your EMF {proposal.human_type} "{title}", and EMF tickets'''
        template = "emails/cfp-reserve-list.txt"
        from_email_ = from_email("SPEAKERS_EMAIL")

    elif reason == "please-finalise":
        # Can be sent before or after scheduling. We want them
        # to update for the line-up, so the earlier the better.
        subject = f'''We need information about your EMF {proposal.human_type} "{title}"'''
        template = "emails/cfp-please-finalise.txt"
        from_email_ = from_email("SPEAKERS_EMAIL")

    elif reason == "check-scheduled-duration":
        # This email is basically the same as "please-finalise" but less urgent
        subject = f'''Your EMF {proposal.human_type} "{title}" is ready to schedule, please check your slot'''
        template = "emails/cfp-check-scheduled-duration.txt"
        from_email_ = from_email("SPEAKERS_EMAIL")

    elif reason == "slot-scheduled":
        subject = f'''Your EMF {proposal.human_type} "{title}" has been scheduled'''
        template = "emails/cfp-slot-scheduled.txt"
        from_email_ = from_email("SPEAKERS_EMAIL")

    elif reason == "slot-moved":
        # TODO: might be nice to highlight which slot has moved
        subject = f'''Your EMF {proposal.human_type} slot has been moved ("{title}")'''
        template = "emails/cfp-slot-moved.txt"
        from_email_ = from_email("SPEAKERS_EMAIL")

    else:
        raise Exception(f"Invalid proposal email type {reason}")

    app.logger.info("Sending %s email for proposal %s", reason, proposal.id)

    msg = EmailMessage(subject, from_email=from_email_, to=[proposal.user.email])
    msg.body = render_template(
        template,
        user=proposal.user,
        proposal=proposal,
        reserve_ticket_link=app.config["RESERVE_LIST_TICKET_LINK"],
    )

    msg.send()


@cfp_review.route("/proposals/<int:proposal_id>/convert", methods=["GET", "POST"])
@admin_required
def convert_proposal(proposal_id: int) -> ResponseReturnValue:
    proposal = get_or_404(db, Proposal, proposal_id)

    form = ConvertProposalForm()
    types = get_args(ProposalType)
    form.new_type.choices = [(t, t.title()) for t in types if t != proposal.type]

    if form.validate_on_submit():
        new_type = form.new_type.data

        old_attributes = proposal.attributes
        proposal.type = new_type  # affects type_info
        new_attributes = proposal.type_info.attributes_cls()
        convert_attributes_between_types(old_attributes, new_attributes)
        proposal.attributes = new_attributes

        if proposal.schedule_item:
            schedule_item: ScheduleItem = proposal.schedule_item

            # There may be new attributes for the proposer to complete.
            # We do not automatically tell them to finalise again, you must send a message.
            schedule_item.state = "unpublished"

            _convert_schedule_item(schedule_item, new_type)

        db.session.commit()

        return redirect(url_for(".update_proposal", proposal_id=proposal.id))

    return render_template("cfp_review/convert_proposal.html", proposal=proposal, form=form)


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

    return render_template("cfp_review/convert_schedule_item.html", schedule_item=schedule_item, form=form)


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


def find_next_proposal_id(prop):
    if not request.args:
        res = get_next_proposal_to(prop, prop.state)
        return res.id if res else None

    proposals, _ = filter_proposal_request()

    # FIXME: index might fail
    idx = proposals.index(prop) + 1
    if len(proposals) <= idx:
        return None
    return proposals[idx].id


def get_update_proposal_type_form(proposal_type: ProposalType) -> type[UpdateProposalForm]:
    class UpdateProposalFormWithAttributes(UpdateProposalForm):
        pass

    UpdateProposalFormWithAttributes.attributes = FormField(
        UPDATE_PROPOSAL_ATTRIBUTES_FORM_TYPES[proposal_type]
    )

    return UpdateProposalFormWithAttributes


@cfp_review.route("/proposals/<int:proposal_id>", methods=["GET", "POST"])
@admin_required
def update_proposal(proposal_id: int) -> ResponseReturnValue:
    def flash_commit_and_go(msg: str, next_page: str, proposal_id: int | None = None) -> ResponseReturnValue:
        flash(msg)
        app.logger.info(msg)
        db.session.commit()

        return redirect(url_for(next_page, proposal_id=proposal_id))

    proposal = get_or_404(db, Proposal, proposal_id)
    next_id = find_next_proposal_id(proposal)

    Form = get_update_proposal_type_form(proposal.type)
    form = Form(obj=proposal)
    form.user_will_have_ticket.data = proposal.user.will_have_ticket

    # TODO: this could move to UpdateProposalForm.__init__
    tags = db.session.scalars(select(Tag).order_by(Tag.tag))
    form.tags.choices = [(t.tag, t.tag) for t in tags]

    if form.validate_on_submit():
        form.populate_obj(proposal)
        proposal.user.will_have_ticket = form.user_will_have_ticket.data

        if form.update.data:
            msg = f"Updating proposal {proposal_id}"
            proposal.state = form.state.data

        elif form.reject.data or form.reject_with_message.data:
            msg = f"Rejecting proposal {proposal_id}"
            proposal.state = "rejected"

            if form.reject_with_message.data:
                proposal.rejected_email_sent = True
                send_email_for_proposal(proposal, reason="rejected")

        elif form.accept.data:
            msg = f"Manually accepting proposal {proposal_id}"
            proposal.state = "accepted"

            if not proposal.schedule_item:
                schedule_item = proposal.create_schedule_item()
                db.session.add(schedule_item)

            send_email_for_proposal(proposal, reason="accepted")

        elif form.checked.data:
            if proposal.type_info.review_type == "manual":
                msg = f"Sending proposal {proposal_id} for manual review"
                proposal.state = "manual-review"
            elif proposal.type_info.review_type == "anonymous":
                msg = f"Sending proposal {proposal_id} for anonymisation"
                proposal.state = "checked"
            else:
                msg = f"Not changing state for automatically accepted proposal {proposal_id}"

            if not next_id:
                return flash_commit_and_go(msg, ".proposals")
            return flash_commit_and_go(msg, ".update_proposal", proposal_id=next_id)

        return flash_commit_and_go(msg, ".update_proposal", proposal_id=proposal_id)

    return render_template(
        "cfp_review/proposal.html",
        proposal=proposal,
        form=form,
        next_id=next_id,
    )


@cfp_review.route("/proposals/<int:proposal_id>/create-schedule-item", methods=["POST"])
@admin_required
def create_schedule_item_from_proposal(proposal_id: int) -> ResponseReturnValue:
    """
    This is usually done on acceptance, but there might be a reason to pre-populate
    a schedule with data before we tell the user that their talk has been accepted.
    """
    proposal = get_or_404(db, Proposal, proposal_id)
    if proposal.schedule_item:
        flash("Proposal already has a schedule item")
        return redirect(url_for(".update_proposal", proposal_id=proposal.id))

    schedule_item = proposal.create_schedule_item()
    db.session.add(schedule_item)
    db.session.commit()

    return redirect(url_for(".update_schedule_item", schedule_item_id=schedule_item.id))


def get_update_schedule_item_type_form(schedule_item_type: ScheduleItemType) -> type[UpdateScheduleItemForm]:
    class UpdateScheduleItemFormWithAttributes(UpdateScheduleItemForm):
        pass

    UpdateScheduleItemFormWithAttributes.attributes = FormField(
        UPDATE_SCHEDULE_ITEM_ATTRIBUTES_FORM_TYPES[schedule_item_type]
    )

    return UpdateScheduleItemFormWithAttributes


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
        "cfp_review/schedule_item.html",
        schedule_item=schedule_item,
        form=form,
        occurrence_form=occurrence_form,
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


def get_update_occurrence_type_form(schedule_item_type: ScheduleItemType) -> type[UpdateOccurrenceForm]:
    type_info = SCHEDULE_ITEM_INFOS[schedule_item_type]
    if not type_info.supports_lottery:
        return UpdateOccurrenceForm

    class UpdateOccurrenceFormWithLottery(UpdateOccurrenceForm):
        pass

    UpdateOccurrenceFormWithLottery.lottery = FormField(LotteryForm)

    return UpdateOccurrenceFormWithLottery


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
        "cfp_review/occurrence.html",
        schedule_item=occurrence.schedule_item,
        occurrence=occurrence,
        form=form,
    )


def sort_messages(messages: list[Proposal]) -> None:
    sort_keys: dict[str, Callable[[Proposal], Any]] = {
        "unread": lambda p: (p.get_unread_count(current_user) > 0, p.messages[-1].created),
        "date": lambda p: p.messages[-1].created,
        "from": lambda p: p.user.name,
        "title": lambda p: p.title,
        "count": lambda p: len(p.messages),
    }

    sort_by_key = request.args.get("sort_by", "unread")
    reverse = bool(request.args.get("reverse"))
    # If unread sort order we have to have unread on top which means reverse sort
    if sort_by_key is None or sort_by_key == "unread":
        reverse = True

    messages.sort(
        key=sort_keys.get(sort_by_key, sort_keys["unread"]),
        reverse=reverse,
    )


@cfp_review.route("/messages")
@admin_required
def messages():
    proposals_with_messages_query = (
        select(Proposal)
        .join(Proposal.messages)
        .order_by(ProposalMessage.has_been_read, ProposalMessage.created.desc())
        .options(joinedload(Proposal.messages))
    )

    filter_type = request.args.get("type")
    if filter_type:
        proposals_with_messages_query = proposals_with_messages_query.filter(Proposal.type == filter_type)
    else:
        filter_type = "all"

    proposals_with_messages = list(db.session.scalars(proposals_with_messages_query).unique())

    sort_messages(proposals_with_messages)

    return render_template(
        "cfp_review/messages.html",
        proposals_with_messages=proposals_with_messages,
        type=filter_type,
    )


@cfp_review.route("/proposals/<int:proposal_id>/message", methods=["GET", "POST"])
@admin_required
def message_proposer(proposal_id):
    form = SendMessageForm()
    proposal = get_or_404(db, Proposal, proposal_id)

    if form.validate_on_submit():
        if form.send.data:
            msg = ProposalMessage()
            msg.is_to_admin = False
            msg.from_user_id = current_user.id
            msg.proposal_id = proposal_id
            msg.message = form.message.data

            db.session.add(msg)
            db.session.commit()

            app.logger.info("Sending message from %s to %s", current_user.id, proposal.user_id)

            msg_url = external_url("cfp.proposal_messages", proposal_id=proposal_id)
            msg = EmailMessage(
                "New message about your EMF proposal",
                from_email=from_email("CONTENT_EMAIL"),
                to=[proposal.user.email],
            )
            msg.body = render_template(
                "cfp_review/email/new_message.txt",
                url=msg_url,
                to_user=proposal.user,
                from_user=current_user,
                proposal=proposal,
            )
            msg.send()

        count = proposal.mark_messages_read(current_user)
        db.session.commit()
        app.logger.info(f"Marked {count} messages to admin on proposal {proposal.id} as read")

        return redirect(url_for(".message_proposer", proposal_id=proposal_id))

    # Admin can see all messages sent in relation to a proposal
    messages = ProposalMessage.query.filter_by(proposal_id=proposal_id).order_by("created").all()

    return render_template(
        "cfp_review/message_proposer.html",
        form=form,
        messages=messages,
        proposal=proposal,
    )


VersionedEntityType = Literal["proposal", "schedule-item", "occurrence"]


@cfp_review.route("/versions/<entity_type>")
@admin_required
def entity_changelog(entity_type: VersionedEntityType) -> ResponseReturnValue:
    if entity_type == "proposal":
        version_cls = version_class(Proposal)
    elif entity_type == "schedule-item":
        version_cls = version_class(ScheduleItem)
    elif entity_type == "occurrence":
        version_cls = version_class(Occurrence)
    else:
        abort(404)

    size = int(request.args.get("size", "100"))
    versions = version_cls.query.order_by(version_cls.transaction_id.desc(), version_cls.modified.desc())
    paged_versions = db.paginate(versions, per_page=size, error_out=False)

    return render_template(
        "cfp_review/entity_changelog.html", versions=paged_versions, entity_type=entity_type
    )


@cfp_review.route("/versions/<entity_type>/<int:entity_id>")
@admin_required
def entity_latest_version(entity_type: VersionedEntityType, entity_id: int) -> ResponseReturnValue:
    entity: Proposal | ScheduleItem | Occurrence
    if entity_type == "proposal":
        entity = get_or_404(db, Proposal, entity_id)
    elif entity_type == "schedule-item":
        entity = get_or_404(db, ScheduleItem, entity_id)
    elif entity_type == "occurrence":
        entity = get_or_404(db, Occurrence, entity_id)
    else:
        abort(404)

    last_txn_id = list(entity.versions)[-1].transaction_id  # type: ignore[union-attr]
    return redirect(
        url_for(".entity_version", entity_type=entity_type, entity_id=entity_id, txn_id=last_txn_id)
    )


@cfp_review.route("/versions/<entity_type>/<int:entity_id>/<int:txn_id>", methods=["GET", "POST"])
@admin_required
def entity_version(entity_type: VersionedEntityType, entity_id: int, txn_id: int) -> ResponseReturnValue:
    entity: Proposal | ScheduleItem | Occurrence
    if entity_type == "proposal":
        entity = get_or_404(db, Proposal, entity_id)
    elif entity_type == "schedule-item":
        entity = get_or_404(db, ScheduleItem, entity_id)
    elif entity_type == "occurrence":
        entity = get_or_404(db, Occurrence, entity_id)
    else:
        abort(404)

    form = ReversionForm()
    version = entity.versions.filter_by(transaction_id=txn_id).one()  # type: ignore[union-attr]

    if form.validate_on_submit():
        app.logger.info(f"Reverting {entity_type} {entity_id} to transaction {txn_id}")
        version.revert()
        db.session.commit()
        return redirect(url_for(".entity_latest_version", entity_type=entity_type, entity_id=entity_id))

    return render_template(
        "cfp_review/entity_version.html",
        form=form,
        entity_type=entity_type,
        entity=entity,
        version=version,
    )


@cfp_review.route("/message-batch", methods=["GET", "POST"])
@admin_required
def message_batch():
    proposals, is_filtered = filter_proposal_request()

    form = SendMessageForm()
    if form.validate_on_submit():
        if form.send.data:
            for proposal in proposals:
                msg = ProposalMessage()
                msg.is_to_admin = False
                msg.from_user_id = current_user.id
                msg.proposal_id = proposal.id
                msg.message = form.message.data

                db.session.add(msg)
                db.session.commit()

                app.logger.info("Sending message from %s to %s", current_user.id, proposal.user_id)

                msg_url = external_url("cfp.proposal_messages", proposal_id=proposal.id)
                msg = EmailMessage(
                    "New message about your EMF proposal",
                    from_email=from_email("CONTENT_EMAIL"),
                    to=[proposal.user.email],
                )
                msg.body = render_template(
                    "cfp_review/email/new_message.txt",
                    url=msg_url,
                    to_user=proposal.user,
                    from_user=current_user,
                    proposal=proposal,
                )
                msg.send()

            flash(f"Messaged {len(proposals)} proposals", "info")
            return redirect(url_for(".proposals", **request.args))

    return render_template("cfp_review/message_batch.html", form=form, proposals=proposals)


def sort_for_vote_summary(proposals_with_state_counts: list[tuple[Proposal, dict[str, int]]]) -> None:
    sort_keys: dict[str, Callable[[tuple[Proposal, dict[str, int]]], Any]] = {
        # Notes == unread first then by date
        "notes": lambda p: (
            p[0].get_unread_vote_note_count() > 0,
            p[0].get_total_vote_note_count(),
        ),
        "date": lambda p: p[0].created,
        "title": lambda p: p[0].title.lower(),
        "votes": lambda p: p[1].get("voted", 0),
        "blocked": lambda p: p[1].get("blocked", 0),
        "recused": lambda p: p[1].get("recused", 0),
    }

    proposals_with_state_counts.sort(
        key=sort_keys.get(request.args.get("sort_by", "notes"), sort_keys["notes"]),
        reverse=bool(request.args.get("reverse")),
    )


@cfp_review.route("/votes")
@admin_required
def vote_summary() -> ResponseReturnValue:
    proposal_query = select(Proposal).options(joinedload(Proposal.votes)).order_by("modified")
    if not request.args.get("all", None):
        proposal_query = proposal_query.where(Proposal.state == "anonymised")

    proposals = list(db.session.scalars(proposal_query).unique())

    proposals_with_counts = []
    summary: dict[str, int] = defaultdict(int)

    for proposal in proposals:
        state_counts: dict[str, int] = {}
        vote_count = len([v for v in proposal.votes if v.state == "voted"])

        if "min_votes" not in summary or summary["min_votes"] > vote_count:
            summary["min_votes"] = vote_count

        if summary["max_votes"] < vote_count:
            summary["max_votes"] = vote_count

        for v in proposal.votes:
            # Update proposal values
            state_counts.setdefault(v.state, 0)
            state_counts[v.state] += 1

            # Update note stats
            if v.note is not None:
                summary["notes_total"] += 1

            if v.note is not None and not v.has_been_read:
                summary["notes_unread"] += 1

            # State stats
            if v.state in ("voted", "blocked", "recused"):
                summary[v.state + "_total"] += 1

        proposals_with_counts.append((proposal, state_counts))

    # sort_key = lambda p: (p[0].get_unread_vote_note_count() > 0, p[0].created)
    sort_for_vote_summary(proposals_with_counts)

    return render_template(
        "cfp_review/vote_summary.html",
        summary=summary,
        proposals_with_counts=proposals_with_counts,
    )


@cfp_review.route("/proposals/<int:proposal_id>/votes", methods=["GET", "POST"])
@admin_required
def proposal_votes(proposal_id):
    form = UpdateVotesForm()
    proposal = get_or_404(db, Proposal, proposal_id)
    all_votes = {v.id: v for v in proposal.votes}

    if form.validate_on_submit():
        msg = ""
        if form.set_all_stale.data:
            stale_count = 0
            states_to_set = (
                ["voted", "blocked", "recused"] if form.include_recused.data else ["voted", "blocked"]
            )
            for vote in all_votes.values():
                if vote.state in states_to_set:
                    vote.set_state("stale")
                    vote.note = None
                    stale_count += 1

            if stale_count:
                msg = f"Set {stale_count} votes to stale"

        elif form.update.data:
            update_count = 0
            for form_vote in form.votes_to_resolve:
                vote = all_votes[form_vote["id"].data]
                if form_vote.resolve.data and vote.state in ["blocked"]:
                    vote.set_state("resolved")
                    vote.note = None
                    update_count += 1

            if update_count:
                msg = f"Set {update_count} votes to resolved"

        elif form.resolve_all.data:
            resolved_count = 0
            for vote in all_votes.values():
                if vote.state == "blocked":
                    vote.set_state("resolved")
                    vote.note = None
                    resolved_count += 1

        if msg:
            flash(msg)
            app.logger.info(msg)

        # Regardless, set everything to read
        for v in all_votes.values():
            v.has_been_read = True

        db.session.commit()
        return redirect(url_for(".proposal_votes", proposal_id=proposal_id))

    for v_id in all_votes:
        form.votes_to_resolve.append_entry()
        form.votes_to_resolve[-1]["id"].data = v_id

    return render_template("cfp_review/proposal_votes.html", proposal=proposal, form=form, votes=all_votes)


@cfp_review.route("/proposals/<int:proposal_id>/notes", methods=["GET", "POST"])
@admin_required
def proposal_notes(proposal_id):
    form = PrivateNotesForm()
    proposal = get_or_404(db, Proposal, proposal_id)

    if form.validate_on_submit():
        if form.update.data:
            proposal.private_notes = form.private_notes.data

            db.session.commit()

            flash("Updated notes")

        return redirect(url_for(".proposal_notes", proposal_id=proposal_id))

    if proposal.private_notes:
        form.private_notes.data = proposal.private_notes

    return render_template(
        "cfp_review/proposal_notes.html",
        form=form,
        proposal=proposal,
    )


@cfp_review.route("/proposals/<int:proposal_id>/change-owner", methods=["GET", "POST"])
@admin_required
def proposal_change_owner(proposal_id: int) -> ResponseReturnValue:
    form = ChangeProposalOwner()
    proposal = get_or_404(db, Proposal, proposal_id)

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

        proposal.user = user
        db.session.commit()

        msg = f"Transferred ownership of proposal {proposal.id} to {user.name}"
        app.logger.info(msg)
        flash(msg)

        return redirect(url_for(".update_proposal", proposal_id=proposal_id))

    return render_template(
        "cfp_review/change_proposal_owner.html",
        form=form,
        proposal=proposal,
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
        "cfp_review/change_schedule_item_owner.html",
        form=form,
        schedule_item=schedule_item,
    )


@cfp_review.route("/close-round", methods=["GET", "POST"])
@admin_required
def close_round():
    form = CloseRoundForm()
    min_votes = 0

    vote_subquery = (
        ProposalVote.query.with_entities(ProposalVote.proposal_id, func.count("*").label("count"))
        .filter(ProposalVote.state == "voted")
        .group_by("proposal_id")
        .subquery()
    )

    proposals = (
        Proposal.query.with_entities(Proposal, vote_subquery.c.count)
        .join(vote_subquery, Proposal.id == vote_subquery.c.proposal_id)
        .filter(Proposal.state.in_(["anonymised", "reviewed"]))
        .order_by(vote_subquery.c.count.desc())
        .all()
    )

    preview = False
    if form.validate_on_submit():
        if form.confirm.data:
            min_votes = session["min_votes"]
            for prop, vote_count in proposals:
                if vote_count >= min_votes and prop.state != "reviewed":
                    prop.state = "reviewed"

            db.session.commit()
            del session["min_votes"]
            app.logger.info(f"CFP Round closed. Set {len(proposals)} proposals to 'reviewed'")

            return redirect(url_for(".rank"))

        if form.close_round.data:
            preview = True
            session["min_votes"] = form.min_votes.data
            flash(f'Proposals with more than {session["min_votes"]} (blue) will be marked as "reviewed"')

        elif form.cancel.data:
            form.min_votes.data = form.min_votes.default
            if "min_votes" in session:
                del session["min_votes"]

    # Find proposals where the submitter has already had an accepted proposal
    # or another proposal in this list
    duplicates = {}
    for prop, _ in proposals:
        if len(prop.user.proposals) > 1:
            duplicates[prop.user] = prop.user.proposals

    return render_template(
        "cfp_review/close-round.html",
        form=form,
        proposals=proposals,
        duplicates=duplicates,
        preview=preview,
        min_votes=session.get("min_votes"),
    )


@cfp_review.route("/rank", methods=["GET", "POST"])
@admin_required
def rank() -> ResponseReturnValue:
    proposals_query = select(Proposal).where(Proposal.state == "reviewed")

    types = request.args.getlist("type")
    if types:
        proposals_query = proposals_query.filter(Proposal.type.in_(types))

    proposals = list(db.session.scalars(proposals_query))
    form = AcceptanceForm()
    scored_proposals = []

    for proposal in proposals:
        score_list = [v.vote for v in proposal.votes if v.state == "voted"]
        score = calculate_max_normalised_score(score_list)
        scored_proposals.append((proposal, score))

    scored_proposals = sorted(scored_proposals, key=lambda p: p[1], reverse=True)

    preview = False
    if form.validate_on_submit():
        if form.confirm.data:
            min_score = session["min_score"]
            count = 0
            for proposal, score in scored_proposals:
                if score >= min_score:
                    count += 1
                    proposal.state = "accepted"

                    if not proposal.schedule_item:
                        schedule_item = proposal.create_schedule_item()
                        db.session.add(schedule_item)

                    if form.confirm_type.data in (
                        "accepted_unaccepted",
                        "accepted",
                        "accepted_reject",
                    ):
                        send_email_for_proposal(proposal, reason="accepted")

                else:
                    proposal.state = "anonymised"
                    if form.confirm_type.data == "accepted_unaccepted":
                        send_email_for_proposal(proposal, reason="still-considered")

                    elif form.confirm_type.data == "accepted_reject":
                        proposal.state = "rejected"
                        proposal.rejected_email_sent = True
                        send_email_for_proposal(proposal, reason="rejected")

                db.session.commit()

            del session["min_score"]
            msg = f"Accepted {count} {types} proposals; min score: {min_score}"
            app.logger.info(msg)
            flash(msg, "info")
            return redirect(url_for(".proposals", state="accepted"))

        if form.set_score.data:
            preview = True
            session["min_score"] = form.min_score.data
            flash("Blue proposals will be accepted", "info")

        elif form.cancel.data and "min_score" in session:
            del session["min_score"]

    # FIXME: why are performances in here if installations aren't?
    proposal_types: list[ProposalType] = ["talk", "workshop", "performance", "youthworkshop"]
    estimates = {proposal_type: get_cfp_estimate(proposal_type) for proposal_type in proposal_types}

    return render_template(
        "cfp_review/rank.html",
        form=form,
        preview=preview,
        proposals=scored_proposals,
        estimates=estimates,
        min_score=session.get("min_score"),
        types=types,
        proposal_types=proposal_types,
    )


@cfp_review.route("/potential-schedule-changes", methods=["GET", "POST"])
@schedule_required
def potential_schedule_changes() -> ResponseReturnValue:
    occurrences = list(
        db.session.scalars(
            select(Occurrence).where(
                Occurrence.potential_venue_id.isnot(None),
                Occurrence.potential_time.isnot(None),
                Occurrence.scheduled_duration.isnot(None),
            )
        )
    )

    return render_template("cfp_review/potential_schedule_changes.html", occurrences=occurrences)


@cfp_review.route("/scheduler")
@schedule_required
def scheduler() -> ResponseReturnValue:
    occurrences: list[Occurrence] = list(
        db.session.scalars(
            select(Occurrence)
            .where(Occurrence.scheduled_duration.isnot(None))
            .where(
                Occurrence.proposal.has(
                    and_(
                        # FIXME: are these needed?
                        Proposal.state.in_({"accepted", "finalised"}),
                        Proposal.type.in_({"talk", "workshop", "youthworkshop", "performance"}),
                    )
                )
            )
            .options(joinedload(Occurrence.schedule_item).joinedload(ScheduleItem.proposal))
        )
    )

    shown_venues = [
        {"key": v.id, "label": v.name}
        for v in db.session.scalars(select(Venue).order_by(Venue.priority.desc()))
    ]

    venues_to_show = request.args.getlist("venue")
    if venues_to_show:
        shown_venues = [venue for venue in shown_venues if venue["label"] in venues_to_show]

    venue_ids = [venue["key"] for venue in shown_venues]

    occurrence_data = []
    for occurrence in occurrences:
        if occurrence.schedule_item.proposal:
            speakers = [occurrence.schedule_item.proposal.user.id]
        else:
            app.logger.warning(f"Occurrence {occurrence.id} has no associated speakers")
            speakers = []

        # FIXME rename these fields, they're all out of date,
        # and maybe add some proper typing
        # See also cfp.scheduler.Scheduler.get_schedule_data

        export: dict[str, Any] = {
            "id": occurrence.id,
            "duration": occurrence.scheduled_duration,
            "is_potential": False,
            "is_attendee": not occurrence.schedule_item.official_content,
            "speakers": speakers,
            "text": occurrence.schedule_item.title,
            "valid_venues": [v.id for v in occurrence.allowed_venues or occurrence.valid_allowed_venues],
            "valid_time_ranges": [
                {"start": str(p.start), "end": str(p.end)}
                for p in occurrence.get_allowed_time_periods_with_default()
            ],
        }

        if occurrence.scheduled_venue:
            export["venue"] = occurrence.scheduled_venue_id
        if occurrence.potential_venue:
            export["venue"] = occurrence.potential_venue_id
            export["is_potential"] = True

        if occurrence.scheduled_time:
            export["start_date"] = occurrence.scheduled_time
        if occurrence.potential_time:
            export["start_date"] = occurrence.potential_time
            export["is_potential"] = True

        if "start_date" in export:
            # We filter on Occurrence.scheduled_duration.isnot(None)) above
            assert occurrence.scheduled_duration is not None
            export["end_date"] = export["start_date"] + timedelta(minutes=occurrence.scheduled_duration)
            export["start_date"] = str(export["start_date"])
            export["end_date"] = str(export["end_date"])

        # We can't show things that are not yet in a slot!
        # FIXME: Show them somewhere
        if "venue" not in export or "start_date" not in export:
            continue

        # Skip this event if we're filtering out the venue it's currently scheduled in
        if export["venue"] not in venue_ids:
            continue

        occurrence_data.append(export)

    venue_names_by_type = Venue.emf_venue_names_by_type()

    return render_template(
        "cfp_review/scheduler.html",
        shown_venues=shown_venues,
        occurrence_data=occurrence_data,
        default_venues=venue_names_by_type,
    )


@cfp_review.route("/scheduler-update", methods=["GET", "POST"])
@admin_required
def scheduler_update() -> ResponseReturnValue:
    occurrence = get_or_404(db, Occurrence, int(request.form["id"]))
    occurrence.potential_time = dateutil.parser.parse(request.form["time"]).replace(tzinfo=None)
    occurrence.potential_venue_id = int(request.form["venue"])

    changed = True
    if occurrence.potential_time == occurrence.scheduled_time and str(occurrence.potential_venue_id) == str(
        occurrence.scheduled_venue_id
    ):
        occurrence.potential_time = None
        occurrence.potential_venue = None
        changed = False

    db.session.commit()
    return jsonify({"changed": changed})


@cfp_review.route("/clashfinder")
@schedule_required
def clashfinder() -> ResponseReturnValue:
    schedule_items = list(
        db.session.scalars(
            select(ScheduleItem)
            .options(joinedload(ScheduleItem.occurrences))
            .options(joinedload(ScheduleItem.proposal))
            .options(joinedload(ScheduleItem.favourited_by))
        ).unique()
    )

    user_faves: dict[int, list[Occurrence]] = defaultdict(list)
    for schedule_item in schedule_items:
        for user in schedule_item.favourited_by:
            # Don't check state because we want to include potential times/venues
            user_faves[user.id] += schedule_item.occurrences

    popularity: Counter[tuple[Occurrence, Occurrence]] = Counter()
    for occurrences in user_faves.values():
        popularity.update((o1, o2) for o1, o2 in combinations(sorted(occurrences, key=lambda o: o.id), 2))

    clashes = []
    offset = 0
    for (o1, o2), count in popularity.most_common()[:1000]:
        offset += 1
        p1 = o1.schedule_item.proposal
        p2 = o2.schedule_item.proposal
        if not p1 or not p2:
            # TODO: this should be rare, do we flag it up?
            continue

        if p1.state not in {"accepted", "finalised"} or p2.state not in {"accepted", "finalised"}:
            # TODO: this also should be rare, do we flag it up?
            continue

        if o1.overlaps_with(o2):
            clashes.append(
                {
                    "occurrence_1": o1,
                    "occurrence_2": o2,
                    "favourite_count": count,
                    "number": offset,
                }
            )

    return render_template("cfp_review/clashfinder.html", clashes=clashes)


# FIXME: orphans from lightning talk class
def get_remaining_lightning_slots():
    return {}


def get_total_lightning_talk_slots():
    return {}


@cfp_review.route("/lightning-talks")
@schedule_required
def lightning_talks():
    filter_query = {"type": "lightning"}
    if "day" in request.args:
        filter_query["session"] = request.args["day"]

    proposals = ScheduleItem.query.filter_by(**filter_query).filter(ScheduleItem.state != "withdrawn").all()

    remaining_lightning_slots = get_remaining_lightning_slots()

    return render_template(
        "cfp_review/lightning_talks_list.html",
        proposals=proposals,
        remaining_lightning_slots=remaining_lightning_slots,
        total_slots=get_total_lightning_talk_slots(),
    )


@cfp_review.route("/proposals-summary")
@schedule_required
def proposals_summary():
    counts_by_tag = {t.tag: Counter() for t in Tag.query.all()}
    counts_by_tag["untagged"] = Counter()

    counts_by_state = {s: Counter() for s in get_args(ProposalState)}
    counts_by_type = Counter()

    for proposal in Proposal.query.all():
        counts_by_type[proposal.type] += 1
        counts_by_state[proposal.state]["total"] += 1
        counts_by_state[proposal.state][proposal.type] += 1

        for tag in proposal.tags:
            counts_by_tag[tag]["total"] += 1
            counts_by_tag[tag][proposal.type] += 1

        if not proposal.tags:
            counts_by_tag["untagged"]["total"] += 1
            counts_by_tag["untagged"][proposal.type] += 1

    return render_template(
        "cfp_review/proposals_summary.html",
        counts_by_tag=counts_by_tag,
        counts_by_type=counts_by_type,
        counts_by_state=counts_by_state,
    )


@cfp_review.route("/schedule-items-summary")
@schedule_required
def schedule_items_summary():
    counts_by_state = {s: Counter() for s in get_args(ScheduleItemState)}
    counts_by_type = Counter()

    for schedule_item in ScheduleItem.query.all():
        counts_by_type[schedule_item.type] += 1
        counts_by_state[schedule_item.state]["total"] += 1
        counts_by_state[schedule_item.state][schedule_item.type] += 1

    return render_template(
        "cfp_review/schedule_items_summary.html",
        counts_by_type=counts_by_type,
        counts_by_state=counts_by_state,
    )


@cfp_review.route("/confidentiality", methods=["GET", "POST"])
def confidentiality_warning():
    if request.method == "POST" and request.form.get("agree"):
        session["cfp_confidentiality"] = True
        return redirect(get_next_url(default=url_for(".proposals")))

    return render_template("cfp_review/confidentiality_warning.html")


@cfp_review.route("/invite-speaker", methods=["GET", "POST"])
@admin_required
def invite_speaker():
    form = InviteSpeakerForm()

    if form.validate_on_submit():
        email, name, reason = form.email.data, form.name.data, form.invite_reason.data
        user = User(email, name)
        user.cfp_invite_reason = reason

        db.session.add(user)
        db.session.commit()

        app.logger.info(f"{current_user.id} created a new user {user} ({email}) to invite to the cfp")

        code = user.login_code(app.config["SECRET_KEY"])

        return render_template(
            "cfp_review/invite-speaker-complete.html",
            user=user,
            login_code=code,
            proposal_type=form.proposal_type.data,
        )

    return render_template("cfp_review/invite-speaker.html", form=form)


def get_diversity_counts(user_list):
    res = {
        "age": Counter(),
        "gender": Counter(),
        "ethnicity": Counter(),
        "reviewer_tags": Counter(),
        "other": {
            "total": len(user_list),
        },
    }

    for user in user_list:
        if not user.diversity:
            res["age"][""] += 1
            res["gender"][""] += 1
            res["ethnicity"][""] += 1
            continue

        if user.diversity.age:
            res["age"][user.diversity.age] += 1
        else:
            res["age"][""] += 1
        if user.diversity.gender:
            res["gender"][user.diversity.gender] += 1
        else:
            res["gender"][""] += 1
        if user.diversity.ethnicity:
            res["ethnicity"][user.diversity.ethnicity] += 1
        else:
            res["ethnicity"][""] += 1
        for tag in user.cfp_reviewer_tags:
            res["reviewer_tags"][tag] += 1

    res["age"]["not given"] = res["age"][""]
    del res["age"][""]
    res["gender"]["not given"] = res["gender"][""]
    del res["gender"][""]
    res["ethnicity"]["not given"] = res["ethnicity"][""]
    del res["ethnicity"][""]

    return res


@cfp_review.route("/speaker-diversity")
@admin_required
def speaker_diversity():
    speakers = (
        User.query.join(User.proposals)
        .filter(
            User.proposals.any(
                Proposal.state.in_(
                    [
                        "manual-review",
                        "accepted",
                        "finalised",
                    ]
                )
            )
        )
        .all()
    )
    total_counts = get_diversity_counts(speakers)
    # remove tags from the counts as these are reviewer tags and irrelevant here
    total_counts.pop("reviewer_tags")
    total_counts["other"]["missing proposal"] = ""

    invited_speakers = [u for u in speakers if u.is_invited_speaker]
    invited_counts = get_diversity_counts(invited_speakers)
    invited_counts.pop("reviewer_tags")

    invited_counts["other"]["missing proposal"] = len(
        [u for u in User.query.all() if len(u.proposals.all()) == 0]
    )

    return render_template(
        "cfp_review/speaker_diversity.html",
        total_counts=total_counts,
        invited_counts=invited_counts,
    )


@cfp_review.route("/reviewer-diversity")
@admin_required
def reviewer_diversity():
    reviewers = (
        User.query.join(User.permissions)
        .filter(User.permissions.any(Permission.name.in_(["cfp_reviewer"])))
        .all()
    )
    counts = get_diversity_counts(reviewers)
    return render_template("cfp_review/reviewer_diversity.html", counts=counts)


@cfp_review.route("/users/<user_id>", methods=["GET"])
@admin_required
def cfp_user(user_id):
    user = db.get_or_404(User, user_id)
    if not user.proposals:
        abort(404)
    return render_template(
        "cfp_review/cfp_user.html",
        user=user,
    )


@cfp_review.route("/lottery")
@admin_required
def lottery():
    ticketed_occurrences = list(db.session.scalars(select(Occurrence).filter_by(uses_lottery=True)))
    return render_template("cfp_review/lottery.html", ticketed_proposals=ticketed_occurrences)


from . import venues  # noqa
