from collections import defaultdict, Counter
import csv
from datetime import timedelta
from http import HTTPStatus
from io import BytesIO, StringIO
from itertools import combinations
import json

import dateutil
from flask import (
    redirect,
    send_file,
    url_for,
    request,
    abort,
    render_template,
    flash,
    session,
    jsonify,
    current_app as app,
)
from flask_login import current_user
from flask_mailman import EmailMessage
from models.permission import Permission
from sqlalchemy import func, exists, select
from sqlalchemy.orm import joinedload, undefer
from sqlalchemy_continuum.utils import version_class

from main import db, external_url
from .estimation import get_cfp_estimate
from .majority_judgement import calculate_max_normalised_score
from models.cfp import (
    CFPMessage,
    CFPVote,
    FavouriteProposal,
    InvalidVenueException,
    LightningTalkProposal,
    MANUAL_REVIEW_TYPES,
    ORDERED_STATES,
    Proposal,
    Venue,
    WorkshopProposal,
)
from models.cfp_tag import Tag, ProposalTag
from models.user import User
from models.purchase import Ticket
from .forms import (
    UpdateTalkForm,
    UpdatePerformanceForm,
    UpdateWorkshopForm,
    UpdateYouthWorkshopForm,
    UpdateInstallationForm,
    UpdateLightningTalkForm,
    UpdateVotesForm,
    SendMessageForm,
    CloseRoundForm,
    AcceptanceForm,
    ConvertProposalForm,
    AddNoteForm,
    ChangeProposalOwner,
    ReversionForm,
    InviteSpeakerForm,
)
from . import (
    cfp_review,
    admin_required,
    schedule_required,
    get_proposal_sort_dict,
    get_next_proposal_to,
    copy_request_args,
)
from ..common.email import from_email
from ..common.forms import guess_age, guess_gender, guess_ethnicity


@cfp_review.route("/")
def main():
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
    elif val in ["False", "0"]:
        return False
    raise ValueError("Invalid querystring boolean")


def filter_proposal_request() -> tuple[list[Proposal], bool]:
    bool_names = ["one_day", "needs_help", "needs_money", "hide_from_schedule"]
    bool_vals = [request.args.get(n, type=bool_qs) for n in bool_names]
    bool_dict = {n: v for n, v in zip(bool_names, bool_vals) if v is not None}

    proposal_query = Proposal.query.filter_by(**bool_dict)

    filtered = False

    types = request.args.getlist("type")
    if types:
        filtered = True
        proposal_query = proposal_query.filter(Proposal.type.in_(types))

    states = request.args.getlist("state")
    if states:
        filtered = True
        proposal_query = proposal_query.filter(Proposal.state.in_(states))

    show_user_scheduled = request.args.get("show_user_scheduled", type=bool_qs)
    if show_user_scheduled is None or show_user_scheduled is False:
        filtered = False
        proposal_query = proposal_query.filter_by(user_scheduled=False)
    else:
        filtered = True
        proposal_query = proposal_query.filter_by(user_scheduled=True)

    # This block has to be last because it will join to the user table
    needs_ticket = request.args.get("needs_ticket", type=bool_qs)
    if needs_ticket is True:
        filtered = True
        proposal_query = (
            proposal_query.join(Proposal.user)
            .filter_by(will_have_ticket=False)
            .filter(
                ~exists().where(
                    Ticket.state.in_(("paid", "payment-pending"))
                    & (Ticket.type == "admission_ticket")
                    & (Ticket.owner_id == User.id)
                )
            )
        )

    tags = request.args.getlist("tags")
    if "untagged" in tags:
        if len(tags) > 1:
            flash("'untagged' in 'tags' arg, other tags ignored")
        filtered = True
        # join(..outer=True) == left outer join
        proposal_query = proposal_query.join(Proposal.tags, isouter=True).filter(
            Tag.id.is_(None)
        )

    elif tags:
        filtered = True
        proposal_query = proposal_query.join(Proposal.tags).filter(
            Proposal.tags.any(Tag.tag.in_(tags))
        )

    sort_dict = get_proposal_sort_dict(request.args)
    proposal_query = (
        proposal_query.options(joinedload(Proposal.user))
        .options(joinedload("user.owned_tickets"))
        .options(joinedload(Proposal.tags))
        .options(undefer(Proposal.favourite_count))
    )
    proposals = proposal_query.all()
    proposals.sort(**sort_dict)
    return proposals, filtered


@cfp_review.route("/proposals")
@admin_required
def proposals():
    proposals, filtered = filter_proposal_request()
    non_sort_query_string = copy_request_args(request.args)

    if "sort_by" in non_sort_query_string:
        del non_sort_query_string["sort_by"]

    if "reverse" in non_sort_query_string:
        del non_sort_query_string["reverse"]

    tag_counts = dict(
        db.session
        .query(Tag.tag, db.func.count(ProposalTag.c.proposal_id))
        .select_from(Tag)
        .outerjoin(ProposalTag)
        .group_by(Tag.tag)
        .order_by(Tag.tag)
        .all()
    )
    tag_counts = {tag: [0, prop_count] for tag, prop_count in tag_counts.items()}
    for prop in proposals:
        for t in prop.tags:
            tag_counts[t.tag][0] = tag_counts[t.tag][0] + 1

    return render_template(
        "cfp_review/proposals.html",
        proposals=proposals,
        new_qs=non_sort_query_string,
        filtered=filtered,
        total_proposals=Proposal.query.count(),
        tag_counts=tag_counts,
    )


@cfp_review.route("/proposals.<format>")
@admin_required
def export(format: str):
    fields = [
        "id",
        "user.email",
        "user.name",
        "created",
        "modified",
        "state",
        "type",
        "title",
        "description",
        "equipment_required",
        "funding_required",
        "additional_info",
        "length",
        "notice_required",
        "tags",
        "favourite_count",
        "published_names",
        "published_pronouns",
        "published_title",
        "published_description",
        "arrival_period",
        "departure_period",
        "telephone_number",
        "eventphone_number",
    ]

    # Do not call this with untrusted field values
    def get_field(proposal, field_path):
        val = proposal
        for field in field_path.split("."):
            val = getattr(val, field)
        return val

    proposals, _ = filter_proposal_request()
    if format == "csv":
        mime = "text/csv"
        buf = StringIO()
        w = csv.writer(buf)
        # Header row
        w.writerow(fields)
        for p in proposals:
            cells = []
            for field in fields:
                cell = get_field(p, field)
                if field == "tags":
                    cell = ",".join(t.tag for t in cell)
                cells.append(cell)
            w.writerow(cells)
        out = buf.getvalue()
    elif format == "json":
        mime = "application/json"
        out = json.dumps(
            [{a: get_field(p, a) for a in fields} for p in proposals],
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


def send_email_for_proposal(proposal, reason="still-considered", from_address=None):
    if reason == "accepted":
        subject = 'Your EMF proposal "%s" has been accepted!' % proposal.title
        template = "cfp_review/email/accepted_msg.txt"

    elif reason == "still-considered":
        subject = 'We\'re still considering your EMF proposal "%s"' % proposal.title
        template = "cfp_review/email/not_accepted_msg.txt"

    elif reason == "rejected":
        proposal.has_rejected_email = True
        subject = 'Your EMF proposal "%s" was not accepted.' % proposal.title
        template = "emails/cfp-rejected.txt"

    elif reason == "check-your-slot":
        subject = (
            "Your EMF proposal '%s' has been scheduled, please check your slot"
            % proposal.title
        )
        template = "emails/cfp-check-your-slot.txt"

    elif reason == "please-finalise":
        subject = "We need information about your EMF proposal '%s'" % proposal.title
        template = "emails/cfp-please-finalise.txt"

    elif reason == "reserve-list":
        subject = "Your EMF proposal '%s', and EMF tickets" % proposal.title
        template = "emails/cfp-reserve-list.txt"

    elif reason == "scheduled":
        subject = "Your EMF %s has been scheduled ('%s')" % (
            proposal.human_type,
            proposal.title,
        )
        template = "emails/cfp-slot-scheduled.txt"

    elif reason == "moved":
        subject = "Your EMF %s slot has been moved ('%s')" % (
            proposal.human_type,
            proposal.title,
        )
        template = "emails/cfp-slot-moved.txt"

    else:
        raise Exception("Unknown cfp proposal email type %s" % reason)

    app.logger.info("Sending %s email for proposal %s", reason, proposal.id)

    send_from = from_email("CONTENT_EMAIL")
    if from_address:
        send_from = from_address

    msg = EmailMessage(subject, from_email=send_from, to=[proposal.user.email])
    msg.body = render_template(
        template,
        user=proposal.user,
        proposal=proposal,
        reserve_ticket_link=app.config["RESERVE_LIST_TICKET_LINK"],
    )

    msg.send()


@cfp_review.route("/proposals/<int:proposal_id>/convert", methods=["GET", "POST"])
@admin_required
def convert_proposal(proposal_id):
    proposal = Proposal.query.get_or_404(proposal_id)

    form = ConvertProposalForm()
    types = {"talk", "workshop", "youthworkshop", "performance", "installation"}
    form.new_type.choices = [(t, t.title()) for t in types if t != proposal.type]

    if form.validate_on_submit():
        proposal.type = form.new_type.data

        # User time availability can vary based on type, if the type has
        # changed we need to nuke whatever they selected. If we keep previous
        # availability and filter we could end up in a case when tiny amounts
        # overlap and we think that is a hard constraint, when it's actually
        # just that the user was never able to select new times.
        proposal.available_times = None
        # The user didn't select this, but we _do_ allow admins to override
        # things into any venue. When things are converted this is not
        # desirable as it can mean that things that were previously scheduled
        # into a workshop tent stay there when they are now a talk and can be
        # in any stage.
        proposal.allowed_venues = []
        # We also need to put talks that were finalised back into accepted so
        # they are re-notified to finalise, as their availability is now
        # incorrect and there are other form fields they may need to complete.
        if proposal.state == "finalised":
            proposal.state = "accepted"

        db.session.commit()

        proposal = Proposal.query.get_or_404(proposal_id)

        return redirect(url_for(".update_proposal", proposal_id=proposal.id))

    return render_template(
        "cfp_review/convert_proposal.html", proposal=proposal, form=form
    )


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


@cfp_review.route("/proposals/<int:proposal_id>", methods=["GET", "POST"])
@admin_required
def update_proposal(proposal_id):
    def log_and_close(msg, next_page, proposal_id=None):
        flash(msg)
        app.logger.info(msg)
        db.session.commit()

        return redirect(url_for(next_page, proposal_id=proposal_id))

    prop = Proposal.query.get_or_404(proposal_id)
    next_id = find_next_proposal_id(prop)

    if prop.type == "talk":
        form = UpdateTalkForm()
    elif prop.type == "workshop":
        form = UpdateWorkshopForm()
    elif prop.type == "youthworkshop":
        form = UpdateYouthWorkshopForm()
    elif prop.type == "performance":
        form = UpdatePerformanceForm()
    elif prop.type == "installation":
        form = UpdateInstallationForm()
    elif prop.type == "lightning":
        form = UpdateLightningTalkForm()
    else:
        raise Exception("Unknown cfp type {}".format(prop.type))

    form.tags.choices = [(t.tag, t.tag) for t in Tag.query.order_by(Tag.tag).all()]
    form.allowed_venues.choices = [
        (v.id, v.name)
        for v in Venue.query.filter(
            db.or_(
                Venue.allowed_types.any(prop.type),
                Venue.id.in_(v.id for v in prop.get_allowed_venues()),
            )
        )
        .order_by(Venue.priority.desc())
        .all()
    ]

    # Process the POST
    if form.validate_on_submit():
        try:
            form.update_proposal(prop)
        except InvalidVenueException:
            # FIXME: this should just be standard field validator,
            # e.g. validate_allowed_venues. That way it'll show up
            # in the form where the error is.
            flash("Invalid venue")
            return render_template(
                "cfp_review/update_proposal.html",
                proposal=prop,
                form=form,
                next_id=next_id,
            )

        if form.update.data:
            msg = "Updating proposal %s" % proposal_id
            prop.state = form.state.data

        elif form.reject.data or form.reject_with_message.data:
            msg = "Rejecting proposal %s" % proposal_id
            prop.set_state("rejected")

            if form.reject_with_message.data:
                send_email_for_proposal(prop, reason="rejected")

        elif form.accept.data:
            msg = "Manually accepting proposal %s" % proposal_id
            prop.set_state("accepted")
            send_email_for_proposal(prop, reason="accepted")

        elif form.checked.data:
            if prop.type in MANUAL_REVIEW_TYPES:
                msg = "Sending proposal %s for manual review" % proposal_id
                prop.set_state("manual-review")
            else:
                msg = "Sending proposal %s for anonymisation" % proposal_id
                prop.set_state("checked")

            if not next_id:
                return log_and_close(msg, ".proposals")
            return log_and_close(msg, ".update_proposal", proposal_id=next_id)
        return log_and_close(msg, ".update_proposal", proposal_id=proposal_id)

    form.state.data = prop.state
    form.title.data = prop.title
    form.description.data = prop.description
    form.tags.data = [t.tag for t in prop.tags]
    form.equipment_required.data = prop.equipment_required
    form.funding_required.data = prop.funding_required
    form.additional_info.data = prop.additional_info
    form.length.data = prop.length
    form.notice_required.data = prop.notice_required
    form.needs_help.data = prop.needs_help
    form.needs_money.data = prop.needs_money
    form.one_day.data = prop.one_day
    form.will_have_ticket.data = prop.user.will_have_ticket
    form.published_names.data = prop.published_names
    form.published_pronouns.data = prop.published_pronouns
    form.published_title.data = prop.published_title
    form.published_description.data = prop.published_description
    form.arrival_period.data = prop.arrival_period
    form.departure_period.data = prop.departure_period
    form.telephone_number.data = prop.telephone_number
    form.eventphone_number.data = prop.eventphone_number
    form.video_privacy.data = prop.video_privacy
    form.needs_laptop.data = prop.needs_laptop
    form.available_times.data = prop.available_times
    form.content_note.data = prop.content_note
    form.family_friendly.data = prop.family_friendly
    form.thumbnail_url.data = prop.thumbnail_url
    form.c3voc_url.data = prop.c3voc_url
    form.youtube_url.data = prop.youtube_url

    form.user_scheduled.data = prop.user_scheduled
    form.hide_from_schedule.data = prop.hide_from_schedule
    form.manually_scheduled.data = prop.manually_scheduled
    form.allowed_venues.data = [v.id for v in prop.get_allowed_venues()]
    form.allowed_times.data = prop.get_allowed_time_periods_serialised()
    form.scheduled_time.data = prop.scheduled_time
    form.scheduled_duration.data = prop.scheduled_duration
    form.potential_time.data = prop.potential_time

    if prop.scheduled_venue:
        form.scheduled_venue.data = prop.scheduled_venue.name

    if prop.potential_venue:
        form.potential_venue.data = prop.potential_venue.name

    if prop.type == "workshop" or prop.type == "youthworkshop":
        form.attendees.data = prop.attendees
        form.cost.data = prop.cost
        form.participant_equipment.data = prop.participant_equipment
        form.age_range.data = prop.age_range
        form.published_age_range.data = prop.published_age_range
        form.published_cost.data = prop.published_cost
        form.published_participant_equipment.data = prop.published_participant_equipment

        form.requires_ticket.data = prop.requires_ticket
        form.tickets.data = prop.total_tickets
        # FIXME set defaults better?
        form.non_lottery_tickets.data = prop.non_lottery_tickets

        if prop.type == "youthworkshop":
            form.valid_dbs.data = prop.valid_dbs

    elif prop.type == "installation":
        form.size.data = prop.size
        form.installation_funding.data = prop.installation_funding

    elif prop.type == "lightning":
        form.session.data = prop.session
        form.slide_link.data = prop.slide_link

    return render_template(
        "cfp_review/proposal.html", proposal=prop, form=form, next_id=next_id
    )


def get_all_messages_sort_dict(parameters, user):
    sort_keys = {
        "unread": lambda p: (p.get_unread_count(user) > 0, p.messages[-1].created),
        "date": lambda p: p.messages[-1].created,
        "from": lambda p: p.user.name,
        "title": lambda p: p.title,
        "count": lambda p: len(p.messages),
    }

    sort_by_key = parameters.get("sort_by")
    reverse = parameters.get("reverse")
    # If unread sort order we have to have unread on top which means reverse sort
    if sort_by_key is None or sort_by_key == "unread":
        reverse = True
    return {
        "key": sort_keys.get(sort_by_key, sort_keys["unread"]),
        "reverse": bool(reverse),
    }


@cfp_review.route("/messages")
@admin_required
def all_messages():
    filter_type = request.args.get("type")

    # Query from the proposal because that's actually what we display
    proposal_with_message = (
        Proposal.query.join(CFPMessage)
        .filter(Proposal.id == CFPMessage.proposal_id)
        .order_by(CFPMessage.has_been_read, CFPMessage.created.desc())
    )

    if filter_type:
        proposal_with_message = proposal_with_message.filter(
            Proposal.type == filter_type
        )
    else:
        filter_type = "all"

    proposal_with_message = proposal_with_message.all()

    sort_dict = get_all_messages_sort_dict(request.args, current_user)
    proposal_with_message.sort(**sort_dict)

    return render_template(
        "cfp_review/all_messages.html",
        proposal_with_message=proposal_with_message,
        type=filter_type,
    )


@cfp_review.route("/proposals/<int:proposal_id>/message", methods=["GET", "POST"])
@admin_required
def message_proposer(proposal_id):
    form = SendMessageForm()
    proposal = Proposal.query.get_or_404(proposal_id)

    if form.validate_on_submit():
        if form.send.data:
            msg = CFPMessage()
            msg.is_to_admin = False
            msg.from_user_id = current_user.id
            msg.proposal_id = proposal_id
            msg.message = form.message.data

            db.session.add(msg)
            db.session.commit()

            app.logger.info(
                "Sending message from %s to %s", current_user.id, proposal.user_id
            )

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
        app.logger.info(
            "Marked %s messages to admin on proposal %s as read" % (count, proposal.id)
        )

        return redirect(url_for(".message_proposer", proposal_id=proposal_id))

    # Admin can see all messages sent in relation to a proposal
    messages = (
        CFPMessage.query.filter_by(proposal_id=proposal_id).order_by("created").all()
    )

    return render_template(
        "cfp_review/message_proposer.html",
        form=form,
        messages=messages,
        proposal=proposal,
    )


@cfp_review.route("/proposals/versions")
@admin_required
def proposal_versions():
    size = int(request.args.get("size", "100"))
    version_cls = version_class(Proposal)
    versions = version_cls.query.order_by(version_cls.modified.desc())
    paged_versions = db.paginate(versions, per_page=size, error_out=False)

    return render_template("cfp_review/proposal_versions.html", versions=paged_versions)


@cfp_review.route("/proposals/<int:proposal_id>/versions")
@admin_required
def proposal_latest_version(proposal_id):
    prop = Proposal.query.get_or_404(proposal_id)
    last_txn_id = prop.versions[-1].transaction_id
    return redirect(
        url_for(".proposal_version", proposal_id=proposal_id, txn_id=last_txn_id)
    )


@cfp_review.route(
    "/proposals/<int:proposal_id>/versions/<int:txn_id>", methods=["GET", "POST"]
)
@admin_required
def proposal_version(proposal_id, txn_id):
    form = ReversionForm()
    prop = Proposal.query.get_or_404(proposal_id)
    version = prop.versions.filter_by(transaction_id=txn_id).one()

    if form.validate_on_submit():
        # FIXME: when would this ever happen?
        if form.proposal_id.data != proposal_id or form.txn_id.data != txn_id:
            flash("Mismatched Ids, try again")
            return redirect(
                url_for(".proposal_version", proposal_id=proposal_id, txn_id=txn_id)
            )

        app.logger.info(f"reverting proposal {proposal_id} to transaction {txn_id}")
        version.revert()
        db.session.commit()
        return redirect(url_for(".proposal_latest_version", proposal_id=proposal_id))

    form.proposal_id.data = proposal_id
    form.txn_id.data = txn_id

    return render_template(
        "cfp_review/proposal_version.html",
        form=form,
        proposal=prop,
        version=version,
    )


@cfp_review.route("/message_batch", methods=["GET", "POST"])
@admin_required
def message_batch():
    proposals, filtered = filter_proposal_request()

    form = SendMessageForm()
    if form.validate_on_submit():
        if form.send.data:
            for proposal in proposals:
                msg = CFPMessage()
                msg.is_to_admin = False
                msg.from_user_id = current_user.id
                msg.proposal_id = proposal.id
                msg.message = form.message.data

                db.session.add(msg)
                db.session.commit()

                app.logger.info(
                    "Sending message from %s to %s", current_user.id, proposal.user_id
                )

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

            flash("Messaged %s proposals" % len(proposals), "info")
            return redirect(url_for(".proposals", **request.args))

    return render_template(
        "cfp_review/message_batch.html", form=form, proposals=proposals
    )


def get_vote_summary_sort_args(parameters):
    sort_keys = {
        # Notes == unread first then by date
        "notes": lambda p: (
            p[0].get_unread_vote_note_count() > 0,
            p[0].get_total_note_count(),
        ),
        "date": lambda p: p[0].created,
        "title": lambda p: p[0].title.lower(),
        "votes": lambda p: p[1].get("voted", 0),
        "blocked": lambda p: p[1].get("blocked", 0),
        "recused": lambda p: p[1].get("recused", 0),
    }

    sort_by_key = parameters.get("sort_by")
    return {
        "key": sort_keys.get(sort_by_key, sort_keys["notes"]),
        "reverse": bool(parameters.get("reverse")),
    }


@cfp_review.route("/votes")
@admin_required
def vote_summary():
    proposal_query = (
        Proposal.query
        if request.args.get("all", None)
        else Proposal.query.filter_by(state="anonymised")
    )

    proposals = proposal_query.order_by("modified").all()

    proposals_with_counts = []
    summary = {
        "notes_total": 0,
        "notes_unread": 0,
        "blocked_total": 0,
        "recused_total": 0,
        "voted_total": 0,
        "min_votes": None,
        "max_votes": 0,
    }

    for prop in proposals:
        state_counts = {}
        vote_count = len([v for v in prop.votes if v.state == "voted"])

        if summary["min_votes"] is None or summary["min_votes"] > vote_count:
            summary["min_votes"] = vote_count

        if summary["max_votes"] < vote_count:
            summary["max_votes"] = vote_count

        for v in prop.votes:
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

        proposals_with_counts.append((prop, state_counts))

    # sort_key = lambda p: (p[0].get_unread_vote_note_count() > 0, p[0].created)
    sort_args = get_vote_summary_sort_args(request.args)
    proposals_with_counts.sort(**sort_args)

    return render_template(
        "cfp_review/vote_summary.html",
        summary=summary,
        proposals_with_counts=proposals_with_counts,
    )


@cfp_review.route("/proposals/<int:proposal_id>/votes", methods=["GET", "POST"])
@admin_required
def proposal_votes(proposal_id):
    form = UpdateVotesForm()
    proposal = Proposal.query.get_or_404(proposal_id)
    all_votes = {v.id: v for v in proposal.votes}

    if form.validate_on_submit():
        msg = ""
        if form.set_all_stale.data:
            stale_count = 0
            states_to_set = (
                ["voted", "blocked", "recused"]
                if form.include_recused.data
                else ["voted", "blocked"]
            )
            for vote in all_votes.values():
                if vote.state in states_to_set:
                    vote.set_state("stale")
                    vote.note = None
                    stale_count += 1

            if stale_count:
                msg = "Set %s votes to stale" % stale_count

        elif form.update.data:
            update_count = 0
            for form_vote in form.votes_to_resolve:
                vote = all_votes[form_vote["id"].data]
                if form_vote.resolve.data and vote.state in ["blocked"]:
                    vote.set_state("resolved")
                    vote.note = None
                    update_count += 1

            if update_count:
                msg = "Set %s votes to resolved" % update_count

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

    return render_template(
        "cfp_review/proposal_votes.html", proposal=proposal, form=form, votes=all_votes
    )


@cfp_review.route("/proposals/<int:proposal_id>/notes", methods=["GET", "POST"])
@admin_required
def proposal_notes(proposal_id):
    form = AddNoteForm()
    proposal = Proposal.query.get_or_404(proposal_id)

    if form.validate_on_submit():
        if form.send.data:
            proposal.private_notes = form.notes.data

            db.session.commit()

            flash("Updated notes")

        return redirect(url_for(".proposal_notes", proposal_id=proposal_id))

    if proposal.private_notes:
        form.notes.data = proposal.private_notes

    return render_template(
        "cfp_review/proposal_notes.html",
        form=form,
        proposal=proposal,
    )


@cfp_review.route("/proposals/<int:proposal_id>/change_owner", methods=["GET", "POST"])
@admin_required
def proposal_change_owner(proposal_id):
    form = ChangeProposalOwner()
    proposal = Proposal.query.get_or_404(proposal_id)

    if form.validate_on_submit and form.submit.data:
        user = User.get_by_email(form.user_email.data)

        if user and form.user_name.data:
            flash("User, '%s', already exists" % form.user_email.data)
            return redirect(url_for(".proposal_change_owner", proposal_id=proposal_id))

        elif not user and not form.user_name.data:
            flash("New user, %s, needs a name" % form.user_email.data)
            return redirect(url_for(".proposal_change_owner", proposal_id=proposal_id))

        elif not user:
            user = User(form.user_email.data, form.user_name.data)
            db.session.add(user)
            app.logger.info("%s created a new user: %s", current_user.name, user.email)
            flash("Created new user %s" % user.email)

        proposal.user = user
        db.session.commit()
        app.logger.info(
            "Transferred ownership of proposal %i to %s", proposal_id, user.name
        )
        flash("Transferred ownership of proposal %i to %s" % (proposal_id, user.name))

        return redirect(url_for(".update_proposal", proposal_id=proposal_id))

    return render_template(
        "cfp_review/change_proposal_owner.html",
        form=form,
        proposal=proposal,
    )


@cfp_review.route("/close-round", methods=["GET", "POST"])
@admin_required
def close_round():
    form = CloseRoundForm()
    min_votes = 0

    vote_subquery = (
        CFPVote.query.with_entities(CFPVote.proposal_id, func.count("*").label("count"))
        .filter(CFPVote.state == "voted")
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
                    prop.set_state("reviewed")

            db.session.commit()
            del session["min_votes"]
            app.logger.info(
                "CFP Round closed. Set %s proposals to 'reviewed'" % len(proposals)
            )

            return redirect(url_for(".rank"))

        elif form.close_round.data:
            preview = True
            session["min_votes"] = form.min_votes.data
            flash(
                f'Proposals with more than {session["min_votes"]} (blue) will be marked as "reviewed"'
            )

        elif form.cancel.data:
            form.min_votes.data = form.min_votes.default
            if "min_votes" in session:
                del session["min_votes"]

    # Find proposals where the submitter has already had an accepted proposal
    # or another proposal in this list
    duplicates = {}
    for prop, _ in proposals:
        if prop.user.proposals.count() > 1:
            # Only add each proposal once
            if prop.user not in duplicates:
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
def rank():
    proposals = Proposal.query.filter_by(state="reviewed")

    types = request.args.getlist("type")
    if types:
        proposals = proposals.filter(Proposal.type.in_(types))

    proposals = proposals.all()
    form = AcceptanceForm()
    scored_proposals = []

    for prop in proposals:
        score_list = [v.vote for v in prop.votes if v.state == "voted"]
        score = calculate_max_normalised_score(score_list)
        scored_proposals.append((prop, score))

    scored_proposals = sorted(scored_proposals, key=lambda p: p[1], reverse=True)

    preview = False
    if form.validate_on_submit():
        if form.confirm.data:
            min_score = session["min_score"]
            count = 0
            for prop, score in scored_proposals:
                if score >= min_score:
                    count += 1
                    prop.set_state("accepted")
                    if form.confirm_type.data in (
                        "accepted_unaccepted",
                        "accepted",
                        "accepted_reject",
                    ):
                        send_email_for_proposal(prop, reason="accepted")

                else:
                    prop.set_state("anonymised")
                    if form.confirm_type.data == "accepted_unaccepted":
                        send_email_for_proposal(prop, reason="still-considered")

                    elif form.confirm_type.data == "accepted_reject":
                        prop.set_state("rejected")
                        prop.has_rejected_email = True
                        send_email_for_proposal(prop, reason="rejected")

                db.session.commit()

            del session["min_score"]
            msg = "Accepted %s %s proposals; min score: %s" % (count, types, min_score)
            app.logger.info(msg)
            flash(msg, "info")
            return redirect(url_for(".proposals", state="accepted"))

        elif form.set_score.data:
            preview = True
            session["min_score"] = form.min_score.data
            flash("Blue proposals will be accepted", "info")

        elif form.cancel.data and "min_score" in session:
            del session["min_score"]

    proposal_types = ["talk", "workshop", "performance", "youthworkshop"]
    estimates = {
        proposal_type: get_cfp_estimate(proposal_type)
        for proposal_type in proposal_types
    }

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


@cfp_review.route("/potential_schedule_changes", methods=["GET", "POST"])
@schedule_required
def potential_schedule_changes():
    proposals = (
        Proposal.query.filter(
            (Proposal.potential_venue != None)  # noqa: E711
            | (Proposal.potential_time != None)  # noqa: E711
        )
        .filter(Proposal.scheduled_duration.isnot(None))
        .all()
    )

    for proposal in proposals:
        if proposal.scheduled_venue:
            proposal.scheduled_venue_name = proposal.scheduled_venue.name
        if proposal.potential_venue:
            proposal.potential_venue_name = proposal.potential_venue.name

    return render_template(
        "cfp_review/potential_schedule_changes.html", proposals=proposals
    )


@cfp_review.route("/scheduler")
@schedule_required
def scheduler():
    proposals = (
        Proposal.query.filter(Proposal.scheduled_duration.isnot(None))
        .filter(Proposal.is_accepted)
        .filter(Proposal.type.in_(["talk", "workshop", "youthworkshop", "performance"]))
        .all()
    )

    shown_venues = [
        {"key": v.id, "label": v.name}
        for v in Venue.query.order_by(Venue.priority.desc()).all()
    ]

    venues_to_show = request.args.getlist("venue")
    if venues_to_show:
        shown_venues = [
            venue for venue in shown_venues if venue["label"] in venues_to_show
        ]

    venue_ids = [venue["key"] for venue in shown_venues]

    schedule_data = []
    for proposal in proposals:
        export = {
            "id": proposal.id,
            "duration": proposal.scheduled_duration,
            "is_potential": False,
            "is_attendee": False,
            "speakers": [proposal.user.id],
            "text": proposal.display_title,
            "valid_venues": [v.id for v in proposal.get_allowed_venues()],
            "valid_time_ranges": [
                {"start": str(p.start), "end": str(p.end)}
                for p in proposal.get_allowed_time_periods_with_default()
            ],
        }

        if proposal.user_scheduled:
            export["is_attendee"] = True

        if proposal.scheduled_venue:
            export["venue"] = proposal.scheduled_venue_id
        if proposal.potential_venue:
            export["venue"] = proposal.potential_venue_id
            export["is_potential"] = True

        if proposal.scheduled_time:
            export["start_date"] = proposal.scheduled_time
        if proposal.potential_time:
            export["start_date"] = proposal.potential_time
            export["is_potential"] = True

        if "start_date" in export:
            export["end_date"] = export["start_date"] + timedelta(
                minutes=proposal.scheduled_duration
            )
            export["start_date"] = str(export["start_date"])
            export["end_date"] = str(export["end_date"])

        # We can't show things that are not yet in a slot!
        # FIXME: Show them somewhere
        if "venue" not in export or "start_date" not in export:
            continue

        # Skip this event if we're filtering out the venue it's currently scheduled in
        if export["venue"] not in venue_ids:
            continue

        schedule_data.append(export)

    venue_names_by_type = Venue.emf_venue_names_by_type()

    return render_template(
        "cfp_review/scheduler.html",
        shown_venues=shown_venues,
        schedule_data=schedule_data,
        default_venues=venue_names_by_type,
    )


@cfp_review.route("/scheduler_update", methods=["GET", "POST"])
@admin_required
def scheduler_update():
    proposal = Proposal.query.filter_by(id=request.form["id"]).one()
    proposal.potential_time = dateutil.parser.parse(request.form["time"]).replace(
        tzinfo=None
    )
    proposal.potential_venue_id = request.form["venue"]

    changed = True
    if proposal.potential_time == proposal.scheduled_time and str(
        proposal.potential_venue_id
    ) == str(proposal.scheduled_venue_id):
        proposal.potential_time = None
        proposal.potential_venue = None
        changed = False

    db.session.commit()
    return jsonify({"changed": changed})


@cfp_review.route("/clashfinder")
@schedule_required
def clashfinder():
    select_st = select([FavouriteProposal])
    res = db.session.execute(select_st)

    user_counts = defaultdict(list)
    popularity = Counter()
    for user, proposal in res:
        user_counts[user].append(proposal)

    for proposals in user_counts.values():
        popularity.update(combinations(sorted(proposals), 2))

    clashes = []
    offset = 0
    for (id1, id2), count in popularity.most_common()[:1000]:
        offset += 1
        prop1 = Proposal.query.get(id1)
        prop2 = Proposal.query.get(id2)
        if prop1.is_accepted and prop2.is_accepted:
            if prop1.overlaps_with(prop2):
                clashes.append(
                    {
                        "proposal_1": prop1,
                        "proposal_2": prop2,
                        "favourites": count,
                        "number": offset,
                    }
                )

    return render_template("cfp_review/clashfinder.html", clashes=clashes)


@cfp_review.route("/lightning-talks")
@schedule_required
def lightning_talks():
    filter_query = {"type": "lightning"}
    if "day" in request.args:
        filter_query["session"] = request.args["day"]

    proposals = (
        LightningTalkProposal.query.filter_by(**filter_query)
        .filter(LightningTalkProposal.state != "withdrawn")
        .all()
    )

    remaining_lightning_slots = LightningTalkProposal.get_remaining_lightning_slots()

    return render_template(
        "cfp_review/lightning_talks_list.html",
        proposals=proposals,
        remaining_lightning_slots=remaining_lightning_slots,
        total_slots=LightningTalkProposal.get_total_lightning_talk_slots(),
    )


@cfp_review.route("/proposals-summary")
@schedule_required
def proposals_summary():
    counts_by_tag = {t.tag: Counter() for t in Tag.query.all()}
    counts_by_tag["untagged"] = Counter()

    counts_by_state = {s: Counter() for s in ORDERED_STATES}
    counts_by_type = Counter()

    for prop in Proposal.query.all():
        counts_by_type[prop.type] += 1
        counts_by_state[prop.state]["total"] += 1
        counts_by_state[prop.state][prop.type] += 1

        for tag in prop.tags:
            counts_by_tag[tag.tag]["total"] += 1
            counts_by_tag[tag.tag][prop.type] += 1

        if not prop.tags:
            counts_by_tag["untagged"]["total"] += 1
            counts_by_tag["untagged"][prop.type] += 1

    return render_template(
        "cfp_review/proposals_summary.html",
        counts_by_tag=counts_by_tag,
        counts_by_type=counts_by_type,
        counts_by_state=counts_by_state,
    )


@cfp_review.route("/confidentiality", methods=["GET", "POST"])
def confidentiality_warning():
    if request.method == "POST" and request.form.get("agree"):
        session["cfp_confidentiality"] = True
        return redirect(request.args.get("next", url_for(".proposals")))

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

        app.logger.info(
            f"{current_user.id} created a new user {user} ({email}) to invite to the cfp"
        )

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
            res["age"][guess_age(user.diversity.age)] += 1
        else:
            res["age"][""] += 1
        if user.diversity.gender:
            res["gender"][guess_gender(user.diversity.gender)] += 1
        else:
            res["gender"][""] += 1
        if user.diversity.ethnicity:
            res["ethnicity"][guess_ethnicity(user.diversity.ethnicity)] += 1
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
    ticketed_proposals = (
        WorkshopProposal.query.filter_by(requires_ticket=True)
        .filter(Proposal.state.in_(["accepted", "finalised"]))
        .all()
    )
    return render_template("cfp_review/lottery.html", ticketed_proposals=ticketed_proposals)


from . import venues  # noqa
