from flask import Blueprint, request, session, redirect, url_for, abort
from flask_login import current_user
from sqlalchemy import func, or_

from models.cfp import (
    Proposal,
    CFPMessage,
    CFPVote,
    Venue,
    CFP_STATES,
    ORDERED_STATES,
    HUMAN_CFP_TYPES,
)
from ..common import require_permission

cfp_review = Blueprint("cfp_review", __name__)

admin_required = require_permission(
    "cfp_admin"
)  # Decorator to require admin permissions
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

    if (
        not session.get("cfp_confidentiality")
        and request.endpoint != "cfp_review.confidentiality_warning"
    ):
        return redirect(
            url_for("cfp_review.confidentiality_warning", next=request.path)
        )


def sort_by_notice(notice):
    return {"1 week": 0, "1 month": 1, "> 1 month": 2}.get(notice, -1)


def get_proposal_sort_dict(parameters):
    sort_keys = {
        "state": lambda p: (p.state, p.modified, p.title.lower()),
        "date": lambda p: (p.modified, p.title.lower()),
        "type": lambda p: (p.type, p.title.lower()),
        "user": lambda p: (p.user.name.lower(), p.title.lower()),
        "title": lambda p: p.title.lower(),
        "ticket": lambda p: (len(p.user.owned_tickets) > 0, p.title.lower()),
        "notice": lambda p: (sort_by_notice(p.notice_required), p.title.lower()),
        "duration": lambda p: (p.scheduled_duration or 0),
        "favourites": lambda p: (p.favourite_count),
    }

    sort_by_key = parameters.get("sort_by")
    return {
        "key": sort_keys.get(sort_by_key, sort_keys["state"]),
        "reverse": bool(parameters.get("reverse")),
    }


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


def copy_request_args(args):
    """
    Request args is an ImmutableMultiDict which allow multiple entries for a
    single key. This converts one back into a normal dict with lists for keys
    so that they can be re-used for request args.
    """
    return {k: args.getlist(k) for k in args}


@cfp_review.context_processor
def cfp_review_variables():
    unread_count = CFPMessage.query.filter(
        # is_to_admin AND (has_been_read IS null OR has_been_read IS false)
        or_(CFPMessage.has_been_read.is_(False), CFPMessage.has_been_read.is_(None)),
        CFPMessage.is_to_admin.is_(True),
    ).count()

    count_dict = dict(
        Proposal.query.with_entities(Proposal.state, func.count(Proposal.state))
        .group_by(Proposal.state)
        .all()
    )
    proposal_counts = {state: count_dict.get(state, 0) for state in CFP_STATES}

    unread_reviewer_notes = (
        CFPVote.query.join(Proposal)
        .filter(
            Proposal.id == CFPVote.proposal_id,
            Proposal.state == "anonymised",
            or_(CFPVote.has_been_read.is_(False), CFPVote.has_been_read.is_(None)),
        )
        .count()
    )

    return {
        "full_qs": copy_request_args(request.args),
        "ordered_states": ORDERED_STATES,
        "cfp_types": HUMAN_CFP_TYPES,
        "unread_count": unread_count,
        "proposal_counts": proposal_counts,
        "unread_reviewer_notes": unread_reviewer_notes,
        "view_name": request.url_rule.endpoint.replace("cfp_review.", "."),
        "emf_venues": [v.name for v in Venue.emf_venues()],
    }


from . import base  # noqa: F401
from . import review  # noqa: F401
from . import anonymise  # noqa: F401
