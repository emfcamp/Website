"""Admin views for viewing and editing proposals"""

import csv
from collections import Counter
from io import StringIO
from itertools import chain
from typing import Any, get_args

from flask import (
    current_app as app,
)
from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue
from flask_login import current_user
from flask_mailman import EmailMessage
from sqlalchemy import func, select
from wtforms import FormField

from main import db, external_url, get_or_404
from models.content import (
    Proposal,
    ProposalMessage,
    ProposalState,
    ProposalTag,
    ProposalType,
    ScheduleItem,
    Tag,
)
from models.content.attributes import convert_attributes_between_types
from models.user import User

from ..config import config
from . import admin_required, cfp_review, get_next_proposal_to, schedule_required
from .base import filter_proposal_request
from .email import send_email_for_proposal
from .forms import (
    UPDATE_PROPOSAL_ATTRIBUTES_FORM_TYPES,
    ChangeProposalOwner,
    ConvertProposalForm,
    PrivateNotesForm,
    ProposalStateForm,
    SendMessageForm,
    UpdateProposalForm,
    UpdateVotesForm,
)
from .schedule_item import _convert_schedule_item


def find_next_proposal_id(prop):
    if not request.args:
        res = get_next_proposal_to(prop, prop.state)
        return res.id if res else None

    proposals, _ = filter_proposal_request()

    try:
        idx = proposals.index(prop) + 1
    except ValueError:
        return None

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


def render_proposal_template(path: str, proposal: Proposal, **args: Any) -> str:
    return render_template(
        path,
        proposal=proposal,
        state_form=ProposalStateForm(proposal),
        next_id=find_next_proposal_id(proposal),
        **args,
    )


def flash_commit_and_go(msg: str, next_page: str, proposal_id: int | None = None) -> ResponseReturnValue:
    flash(msg)
    app.logger.info(msg)
    db.session.commit()

    return redirect(url_for(next_page, proposal_id=proposal_id))


@cfp_review.route("/proposals")
@admin_required
def proposals() -> ResponseReturnValue:

    default_columns = ["ticket", "date", "state", "type", "notice", "duration", "user", "title"]
    columns = request.args.getlist("cols") or default_columns

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

    if request.args.get("format") == "csv":
        data = [proposal.to_dict() for proposal in proposals]
        # Don't use a set to ensure uniqueness here because we want to preserve key ordering
        fields = list(dict.fromkeys(chain.from_iterable(item.keys() for item in data)))
        buf = StringIO()
        writer = csv.DictWriter(buf, fieldnames=fields)
        writer.writeheader()
        for row in data:
            writer.writerow(row)
        return app.response_class(response=buf.getvalue(), status=200, mimetype="text/csv")

    return render_template(
        "cfp_review/proposal/proposals.html",
        proposals=proposals,
        new_qs=non_sort_query_string,
        is_filtered=is_filtered,
        total_proposals=db.session.scalar(select(func.count(Proposal.id))),
        tag_counts=tag_counts,
        columns=columns,
    )


@cfp_review.route("/proposals/<int:proposal_id>")
@admin_required
def proposal(proposal_id: int) -> ResponseReturnValue:
    proposal = get_or_404(db, Proposal, proposal_id)
    return render_proposal_template(
        "cfp_review/proposal/main.html",
        proposal,
        notes_form=PrivateNotesForm(proposal),
        all_tags=db.session.scalars(select(Tag).order_by(Tag.tag)),
    )


@cfp_review.route("/proposals-summary")
@schedule_required
def proposals_summary() -> ResponseReturnValue:
    counts_by_tag: dict[str, Counter[str]] = {t.tag: Counter() for t in db.session.query(Tag).all()}
    counts_by_tag["untagged"] = Counter()

    counts_by_state: dict[ProposalState, Counter[str]] = {s: Counter() for s in get_args(ProposalState)}
    counts_by_type: Counter[str] = Counter()

    for proposal in db.session.query(Proposal).all():
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
        "cfp_review/proposal/proposals_summary.html",
        counts_by_tag=counts_by_tag,
        counts_by_type=counts_by_type,
        counts_by_state=counts_by_state,
    )


@cfp_review.route("/proposals/<int:proposal_id>/edit", methods=["GET", "POST"])
@admin_required
def update_proposal(proposal_id: int) -> ResponseReturnValue:
    proposal = get_or_404(db, Proposal, proposal_id)

    Form = get_update_proposal_type_form(proposal.type)
    form = Form(obj=proposal)

    if form.validate_on_submit() and form.update.data:
        form.populate_obj(proposal)
        proposal.user.will_have_ticket = form.user_will_have_ticket.data

        msg = f"Updating proposal {proposal_id}"
        proposal.state = form.state.data
        return flash_commit_and_go(msg, ".proposal", proposal_id=proposal_id)

    if request.method == "GET":
        form.user_will_have_ticket.data = proposal.user.will_have_ticket

    return render_proposal_template(
        "cfp_review/proposal/edit.html",
        proposal,
        form=form,
    )


@cfp_review.route("/proposals/<int:proposal_id>/tags", methods=["POST"])
@admin_required
def proposal_tags(proposal_id: int) -> ResponseReturnValue:
    proposal = get_or_404(db, Proposal, proposal_id)

    if id := request.form.get("delete"):
        tag = db.session.scalars(select(Tag).filter_by(id=id)).one()
        proposal.tags = list(set(proposal.tags) - {tag.tag})
        db.session.commit()

    if request.form.get("add"):
        id = request.form.get("id")
        tag = db.session.scalars(select(Tag).filter_by(id=id)).one()
        proposal.tags = proposal.tags + [tag.tag]
        db.session.commit()

    return redirect(url_for(".proposal", proposal_id=proposal_id))


@cfp_review.route("/proposals/<int:proposal_id>/state", methods=["POST"])
@admin_required
def update_proposal_state(proposal_id: int) -> ResponseReturnValue:
    """Handle admin changes to the proposal state through the actions form."""
    proposal = get_or_404(db, Proposal, proposal_id)
    form = ProposalStateForm(proposal)

    if not form.validate_on_submit():
        return redirect(url_for(".proposal", proposal_id=proposal_id))

    # This depends on the current proposal state
    next_id = find_next_proposal_id(proposal)

    goto_next = False  # Whether to try and send the user to the next proposal
    new_state = form.result()

    old_state = proposal.state

    if new_state == "rejected" and form.reject_with_message.data:
        proposal.reject()
        send_email_for_proposal(proposal, reason="rejected")
        proposal.rejected_email_sent = True
    elif new_state == "accepted":
        proposal.accept()
        send_email_for_proposal(proposal, reason="accepted")
    elif new_state == "withdrawn":
        proposal.withdraw()
    elif new_state == "checked":
        goto_next = True
        if proposal.type_info.review_type == "manual":
            new_state = "manual-review"
        elif proposal.type_info.review_type != "anonymous":
            # TODO: work out whether this will ever happen, and stop it
            raise ValueError("Invalid attempt to mark proposal as checked")

    msg = f"Admin state change for proposal {proposal_id}: {old_state} -> {new_state}"

    proposal.state = new_state
    db.session.commit()

    if goto_next:
        if next_id:
            return flash_commit_and_go(msg, ".proposal", proposal_id=next_id)
        return flash_commit_and_go(msg, ".proposals")

    return flash_commit_and_go(msg, ".proposal", proposal_id=proposal_id)


@cfp_review.route("/proposals/<int:proposal_id>/message", methods=["GET", "POST"])
@admin_required
def message_proposer(proposal_id: int) -> ResponseReturnValue:
    form = SendMessageForm()
    proposal = get_or_404(db, Proposal, proposal_id)

    if form.validate_on_submit():
        if form.send.data:
            assert form.message.data
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
                from_email=config.from_email("CONTENT_EMAIL"),
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
    messages = db.session.query(ProposalMessage).filter_by(proposal_id=proposal_id).order_by("created").all()

    return render_proposal_template(
        "cfp_review/proposal/messages.html",
        proposal,
        form=form,
        messages=messages,
    )


@cfp_review.route("/proposals/<int:proposal_id>/votes", methods=["GET", "POST"])
@admin_required
def proposal_votes(proposal_id: int) -> ResponseReturnValue:
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

    return render_proposal_template("cfp_review/proposal/votes.html", proposal, form=form, votes=all_votes)


@cfp_review.route("/proposals/<int:proposal_id>/notes", methods=["POST"])
@admin_required
def proposal_notes(proposal_id: int) -> ResponseReturnValue:
    proposal = get_or_404(db, Proposal, proposal_id)
    form = PrivateNotesForm(proposal)

    if form.validate_on_submit():
        if form.update.data:
            proposal.private_notes = form.private_notes.data

            db.session.commit()

            flash("Updated notes")

    return redirect(url_for(".proposal", proposal_id=proposal_id))


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

        return redirect(url_for(".proposal", proposal_id=proposal_id))

    return render_proposal_template("cfp_review/proposal/change_owner.html", proposal, form=form)


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

        return redirect(url_for(".proposal", proposal_id=proposal.id))

    return render_proposal_template("cfp_review/proposal/convert.html", proposal, form=form)
