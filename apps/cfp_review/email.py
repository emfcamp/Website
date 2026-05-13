"""Proposal email helpers"""

from typing import Literal

from flask import (
    current_app as app,
)
from flask import render_template
from flask_mailman import EmailMessage

from models.content import Proposal

from ..config import config

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
    from_email_ = config.from_email("CONTENT_EMAIL")
    title = (proposal.schedule_item and proposal.schedule_item.title) or proposal.title

    if reason == "accepted":
        subject = f'''Your EMF {proposal.human_type} "{title}" has been accepted!'''
        template = "cfp_review/email/accepted_msg.txt"

    elif reason == "still-considered":
        subject = f'''We're still considering your EMF {proposal.human_type} "{title}"'''
        template = "cfp_review/email/still_considering.txt"

    elif reason == "rejected":
        # remember to set rejected_email_sent
        subject = f'''Your EMF {proposal.human_type} "{title}" was not accepted.'''
        template = "emails/cfp-rejected.txt"

    elif reason == "reserve-list":
        subject = f'''Your EMF {proposal.human_type} "{title}", and EMF tickets'''
        template = "emails/cfp-reserve-list.txt"
        from_email_ = config.from_email("SPEAKERS_EMAIL")

    elif reason == "please-finalise":
        # Can be sent before or after scheduling. We want them
        # to update for the line-up, so the earlier the better.
        subject = f'''We need information about your EMF {proposal.human_type} "{title}"'''
        template = "emails/cfp-please-finalise.txt"
        from_email_ = config.from_email("SPEAKERS_EMAIL")

    elif reason == "check-scheduled-duration":
        # This email is basically the same as "please-finalise" but less urgent
        subject = f'''Your EMF {proposal.human_type} "{title}" is ready to schedule, please check your slot'''
        template = "emails/cfp-check-scheduled-duration.txt"
        from_email_ = config.from_email("SPEAKERS_EMAIL")

    elif reason == "slot-scheduled":
        subject = f'''Your EMF {proposal.human_type} "{title}" has been scheduled'''
        template = "emails/cfp-slot-scheduled.txt"
        from_email_ = config.from_email("SPEAKERS_EMAIL")

    elif reason == "slot-moved":
        # TODO: might be nice to highlight which slot has moved
        subject = f'''Your EMF {proposal.human_type} slot has been moved ("{title}")'''
        template = "emails/cfp-slot-moved.txt"
        from_email_ = config.from_email("SPEAKERS_EMAIL")

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
