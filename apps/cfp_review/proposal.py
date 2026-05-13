"""Admin views for viewing and editing proposals"""

from typing import get_args

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
from sqlalchemy import select
from wtforms import FormField

from main import db, external_url, get_or_404
from models.content import Proposal, ProposalMessage, ProposalType, ScheduleItem, Tag
from models.content.attributes import convert_attributes_between_types
from models.user import User

from ..config import config
from . import admin_required, cfp_review, get_next_proposal_to
from .base import _convert_schedule_item, filter_proposal_request
from .email import send_email_for_proposal
from .forms import (
    UPDATE_PROPOSAL_ATTRIBUTES_FORM_TYPES,
    ChangeProposalOwner,
    ConvertProposalForm,
    PrivateNotesForm,
    SendMessageForm,
    UpdateProposalForm,
    UpdateVotesForm,
)


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
            proposal.accept_proposal()

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
        "cfp_review/proposal/edit.html",
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
    messages = ProposalMessage.query.filter_by(proposal_id=proposal_id).order_by("created").all()

    return render_template(
        "cfp_review/proposal/messages.html",
        form=form,
        messages=messages,
        proposal=proposal,
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

    return render_template("cfp_review/proposal/votes.html", proposal=proposal, form=form, votes=all_votes)


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
        "cfp_review/proposal/notes.html",
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
        "cfp_review/proposal/change_owner.html",
        form=form,
        proposal=proposal,
    )


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

    return render_template("cfp_review/proposal/convert.html", proposal=proposal, form=form)
