import pendulum  # preferred over datetime
from collections import defaultdict
from werkzeug.datastructures import MultiDict
from flask_login import current_user
from slugify import slugify_unicode as slugify

from models import event_year
from models.cfp import Proposal, Venue

from main import external_url
from . import event_tz


def _get_proposal_dict(proposal: Proposal, favourites_ids):
    res = {
        "id": proposal.id,
        "slug": proposal.slug,
        "start_date": event_tz.localize(proposal.start_date),
        "end_date": event_tz.localize(proposal.end_date) if proposal.end_date else None,
        "venue": proposal.scheduled_venue.name,
        "latlon": proposal.latlon,
        "map_link": proposal.map_link,
        "title": proposal.display_title,
        "speaker": proposal.published_names or proposal.user.name,
        "pronouns": proposal.published_pronouns,
        "user_id": proposal.user.id,
        "description": proposal.published_description or proposal.description,
        "type": proposal.type,
        "may_record": proposal.may_record,
        "is_fave": proposal.id in favourites_ids,
        "is_family_friendly": proposal.family_friendly,
        "is_from_cfp": not proposal.user_scheduled,
        "content_note": proposal.content_note,
        "source": "database",
        "link": external_url(
            ".item",
            year=event_year(),
            proposal_id=proposal.id,
            slug=proposal.slug,
        ),
    }
    if proposal.type in ["workshop", "youthworkshop"]:
        res["cost"] = proposal.display_cost
        res["equipment"] = proposal.display_participant_equipment
        res["age_range"] = proposal.display_age_range
        res["attendees"] = proposal.attendees
        res["requires_ticket"] = proposal.requires_ticket
    video_res = {}
    if proposal.c3voc_url:
        video_res["ccc"] = proposal.c3voc_url
    if proposal.youtube_url:
        video_res["youtube"] = proposal.youtube_url
    if proposal.thumbnail_url:
        video_res["preview_image"] = proposal.thumbnail_url
    video_res["recording_lost"] = proposal.video_recording_lost
    if video_res:
        res["video"] = video_res
    return res


def _filter_obj_to_dict(filter_obj):
    """Request.args uses a MulitDict this lets us pass filter_obj as plain dicts
    and have everything work as expected.
    """
    if type(filter_obj) == MultiDict:
        return filter_obj.to_dict()
    return filter_obj


def _get_scheduled_proposals(filter_obj={}, override_user=None):
    filter_obj = _filter_obj_to_dict(filter_obj)
    if override_user:
        user = override_user
    else:
        user = current_user

    if user.is_anonymous:
        proposal_favourites = []
    else:
        proposal_favourites = [f.id for f in user.favourites]

    schedule = Proposal.query.filter(
        Proposal.is_accepted,
        Proposal.scheduled_time.isnot(None),
        Proposal.scheduled_venue_id.isnot(None),
        Proposal.scheduled_duration.isnot(None),
        Proposal.hide_from_schedule.isnot(True),
    ).all()

    schedule = [_get_proposal_dict(p, proposal_favourites) for p in schedule]

    if "is_favourite" in filter_obj and filter_obj["is_favourite"]:
        schedule = [s for s in schedule if s.get("is_fave", False)]

    if "venue" in filter_obj:
        schedule = [s for s in schedule if s["venue"] in filter_obj["venue"]]

    return schedule


def _get_upcoming(filter_obj={}, override_user=None):
    filter_obj = _filter_obj_to_dict(filter_obj)
    now = pendulum.now(event_tz)
    proposals = _get_scheduled_proposals(filter_obj, override_user)
    upcoming = [_convert_time_to_str(p) for p in proposals if p["end_date"] > now]

    upcoming = sorted(upcoming, key=lambda p: p["start_date"])

    limit = int(filter_obj.get("limit", 2))

    # Already filtered by venue in _get_scheduled_proposals
    if limit <= 0:
        return upcoming

    by_venue = defaultdict(list)
    for p in upcoming:
        by_venue[p["venue"]].append(p)

    res = {slugify(k.lower()): v[:limit] for k, v in by_venue.items()}

    return res


def _convert_time_to_str(event):
    event["start_time"] = event["start_date"].strftime("%H:%M")
    event["end_time"] = event["end_date"].strftime("%H:%M")

    event["start_date"] = event["start_date"].strftime("%Y-%m-%d %H:%M:00")
    event["end_date"] = event["end_date"].strftime("%Y-%m-%d %H:%M:00")
    return event


def _get_priority_sorted_venues(venues_to_allow):
    main_venues = Venue.query.filter().all()
    main_venue_names = [(v.name, "main", v.priority) for v in main_venues]

    res = []
    seen_names = []
    for venue in main_venue_names:
        name = venue[0]
        if name not in seen_names and name in venues_to_allow:
            seen_names.append(name)
            res.append(
                {
                    "key": slugify(name),
                    "label": name,
                    "source": venue[1],
                    "order": venue[2],
                }
            )

    res = sorted(res, key=lambda v: v["order"], reverse=True)
    return res
