from typing import Any, Callable, get_args
from flask import Blueprint, request, session, redirect, url_for, abort
from flask_login import current_user
from sqlalchemy import func, or_, select

from models.cfp import (
    PROPOSAL_INFOS,
    SCHEDULE_ITEM_INFOS,
    Proposal,
    ProposalMessage,
    ProposalType,
    ProposalVote,
    ScheduleItem,
    ScheduleItemState,
    ScheduleItemType,
    Venue,
    ProposalState,
)
from ..common import require_permission
from main import db

cfp_review = Blueprint("cfp_review", __name__)

admin_required = require_permission("cfp_admin")  # Decorator to require admin permissions
anon_required = require_permission("cfp_anonymiser")
review_required = require_permission("cfp_reviewer")
schedule_required = require_permission("cfp_schedule")

CFP_PERMISSIONS = {
    "admin",
    "cfp_admin",
    "cfp_anonymiser",
    "cfp_reviewer",
    "cfp_schedule",
}


@cfp_review.before_request
def before_request():
    if not current_user.is_authenticated:
        return redirect(url_for("users.login", next=request.path))

    # Check if the user has any CFP permissions
    if len(set(p.name for p in current_user.permissions) & CFP_PERMISSIONS) == 0:
        abort(404)

    if not session.get("cfp_confidentiality") and request.endpoint != "cfp_review.confidentiality_warning":
        return redirect(url_for("cfp_review.confidentiality_warning", next=request.path))


def sort_by_notice(notice):
    return {"1 week": 0, "1 month": 1, "> 1 month": 2}.get(notice, -1)


def sort_proposals(proposals: list[Proposal]):
    sort_keys: dict[str, Callable[[Proposal], Any]] = {
        "ticket": lambda p: (len(p.user.owned_tickets) > 0, p.title.lower()),
        "date": lambda p: (p.modified, p.title.lower()),
        "state": lambda p: (p.state, p.modified, p.title.lower()),
        "type": lambda p: (p.type, p.title.lower()),
        "notice": lambda p: (sort_by_notice(p.notice_required), p.title.lower()),
        "duration": lambda p: (p.duration or 0),
        "user": lambda p: (p.user.name.lower(), p.title.lower()),
        "title": lambda p: p.title.lower(),
    }

    sort_by_key = request.args.get("sort_by", "state")
    proposals.sort(
        key=sort_keys.get(sort_by_key, sort_keys["state"]),
        reverse=bool(request.args.get("reverse")),
    )


def sort_schedule_items(schedule_items: list[ScheduleItem]):
    sort_keys: dict[str, Callable[[ScheduleItem], Any]] = {
        "date": lambda si: (si.modified, si.title.lower()),
        "state": lambda si: (si.state, si.modified, si.title.lower()),
        "type": lambda si: (si.type, si.title.lower()),
        "official_content": lambda si: si.official_content and "Official" or "Attendee",
        "names": lambda si: (si.names and si.names.lower(), si.title.lower()),
        "title": lambda si: si.title.lower(),
        "favourites": lambda si: si.favourite_count,
    }

    sort_by_key = request.args.get("sort_by", "state")
    schedule_items.sort(
        key=sort_keys.get(sort_by_key, sort_keys["state"]),
        reverse=bool(request.args.get("reverse")),
    )


def get_next_proposal_to(prop, state):
    return (
        Proposal.query.filter(
            Proposal.id != prop.id,
            Proposal.state == state,
            Proposal.modified >= prop.modified,  # ie find something after this one
        )
        .order_by("modified", "id")
        .first()
    )


@cfp_review.context_processor
def cfp_review_variables():
    unread_count = ProposalMessage.query.filter(
        # is_to_admin AND (has_been_read IS null OR has_been_read IS false)
        or_(ProposalMessage.has_been_read.is_(False), ProposalMessage.has_been_read.is_(None)),
        ProposalMessage.is_to_admin.is_(True),
    ).count()

    proposal_count_dict = dict(
        list(db.session.execute(select(Proposal.state, func.count(Proposal.state)).group_by(Proposal.state)))
    )
    proposal_counts = {state: proposal_count_dict.get(state, 0) for state in get_args(ProposalState)}

    schedule_item_count_dict = dict(
        list(
            db.session.execute(
                select(ScheduleItem.state, func.count(ScheduleItem.state)).group_by(ScheduleItem.state)
            )
        )
    )
    schedule_item_counts = {
        state: schedule_item_count_dict.get(state, 0) for state in get_args(ScheduleItemState)
    }

    unread_reviewer_notes = (
        ProposalVote.query.join(Proposal)
        .filter(
            Proposal.id == ProposalVote.proposal_id,
            Proposal.state == "anonymised",
            or_(ProposalVote.has_been_read.is_(False), ProposalVote.has_been_read.is_(None)),
        )
        .count()
    )

    return {
        "full_qs": request.args.to_dict(flat=False),
        "proposal_states": get_args(ProposalState),
        "proposal_types": get_args(ProposalType),
        "PROPOSAL_INFOS": PROPOSAL_INFOS,
        "schedule_item_states": get_args(ScheduleItemState),
        "schedule_item_types": get_args(ScheduleItemType),
        "SCHEDULE_ITEM_INFOS": SCHEDULE_ITEM_INFOS,
        "unread_count": unread_count,
        "proposal_counts": proposal_counts,
        "schedule_item_counts": schedule_item_counts,
        "unread_reviewer_notes": unread_reviewer_notes,
        "view_name": request.url_rule.endpoint.replace("cfp_review.", "."),
        "emf_venues": [v.name for v in Venue.emf_venues()],
    }


from . import base  # noqa: F401
from . import review  # noqa: F401
from . import anonymise  # noqa: F401
from . import sense_check  # noqa: F401
