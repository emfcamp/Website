from flask import Blueprint, request
from sqlalchemy import func, or_

from models.cfp import (
    Proposal,
    CFPMessage,
    CFPVote,
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


def sort_by_notice(notice):
    return {"1 week": 0, "1 month": 1, "> 1 month": 2}.get(notice, -1)


def get_permission_namespace(user, permission):
    for perm in user.permissions:
        perm_name = perm.name
        if perm_name.startswith(permission) and ":" in perm_name:
            _, res = perm_name.split(":")
            return res


def get_proposal_sort_dict(parameters):
    sort_keys = {
        "state": lambda p: (p.state, p.modified, p.title),
        "date": lambda p: (p.modified, p.title),
        "type": lambda p: (p.type, p.title),
        "user": lambda p: (p.user.name, p.title),
        "title": lambda p: p.title,
        "ticket": lambda p: (len(p.user.owned_tickets) > 0, p.title),
        "notice": lambda p: (sort_by_notice(p.notice_required), p.title),
        "duration": lambda p: (p.scheduled_duration or 0),
        "favourites": lambda p: (p.favourite_count),
    }

    sort_by_key = parameters.get("sort_by")
    return {
        "key": sort_keys.get(sort_by_key, sort_keys["state"]),
        "reverse": bool(parameters.get("reverse")),
    }


def get_next_proposal_to(prop, state, type=None):
    if type:
        return (
            Proposal.query.filter(
                Proposal.id != prop.id,
                Proposal.type == type,
                Proposal.state == state,
                Proposal.modified >= prop.modified,  # ie find something after this one
            )
            .order_by("modified", "id")
            .first()
        )
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
    }


from . import base  # noqa: F401
from . import review  # noqa: F401
from . import anonymise  # noqa: F401
