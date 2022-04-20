import pendulum  # preferred over datetime
from collections import defaultdict
from flask_login import current_user
from slugify import slugify_unicode as slugify

from models import event_year
from models.cfp import Proposal, Venue
from models.ical import CalendarSource

from main import external_url
from . import event_tz


def _get_proposal_dict(proposal, favourites_ids):
    res = {
        "id": proposal.id,
        "slug": proposal.slug,
        "start_date": event_tz.localize(proposal.start_date),
        "end_date": event_tz.localize(proposal.end_date),
        "venue": proposal.scheduled_venue.name,
        "latlon": proposal.latlon,
        "map_link": proposal.map_link,
        "title": proposal.display_title,
        "speaker": proposal.published_names or proposal.user.name,
        "user_id": proposal.user.id,
        "description": proposal.published_description or proposal.description,
        "type": proposal.type,
        "may_record": proposal.may_record,
        "is_fave": proposal.id in favourites_ids,
        "source": "database",
        "link": external_url(
            ".line_up_redirect",
            year=event_year(),
            slug=proposal.slug,
            proposal_id=proposal.id,
        ),
    }
    if proposal.type in ["workshop", "youthworkshop"]:
        res["cost"] = proposal.display_cost
        res["equipment"] = proposal.display_participant_equipment
        res["age_range"] = proposal.display_age_range
    return res


def _get_ical_dict(event, favourites_ids):
    res = {
        "id": -event.id,
        "start_date": event_tz.localize(event.start_dt),
        "end_date": event_tz.localize(event.end_dt),
        "venue": event.location or "(Unknown)",
        "latlon": event.latlon,
        "map_link": event.map_link,
        "title": event.summary,
        "speaker": "",
        "user_id": None,
        "description": event.description,
        "type": "talk",
        "may_record": False,
        "is_fave": event.id in favourites_ids,
        "source": "external",
        "link": external_url(
            ".item_external", year=event_year(), slug=event.slug, event_id=event.id
        ),
    }
    if event.type in ["workshop", "youthworkshop"]:
        res["cost"] = event.display_cost
        res["equipment"] = event.display_participant_equipment
        res["age_range"] = event.display_age_range
    return res


def _get_scheduled_proposals(filter_obj={}, override_user=None):
    if override_user:
        user = override_user
    else:
        user = current_user

    if user.is_anonymous:
        proposal_favourites = external_favourites = []
    else:
        proposal_favourites = [f.id for f in user.favourites]
        external_favourites = [f.id for f in user.calendar_favourites]

    schedule = Proposal.query.filter(
        Proposal.state.in_(["accepted", "finished"]),
        Proposal.scheduled_time.isnot(None),
        Proposal.scheduled_venue_id.isnot(None),
        Proposal.scheduled_duration.isnot(None),
    ).all()

    schedule = [_get_proposal_dict(p, proposal_favourites) for p in schedule]

    ical_sources = CalendarSource.query.filter_by(enabled=True, published=True)

    for source in ical_sources:
        for e in source.events:
            d = _get_ical_dict(e, external_favourites)
            d["venue"] = source.mapobj.name
            schedule.append(d)

    if "is_favourite" in filter_obj and filter_obj["is_favourite"]:
        schedule = [s for s in schedule if s.get("is_fave", False)]

    if "venue" in filter_obj:
        schedule = [s for s in schedule if s["venue"] in filter_obj.getlist("venue")]

    return schedule


def _get_upcoming(filter_obj={}, override_user=None):
    # now = pendulum.now(event_tz)
    now = pendulum.datetime(2018, 8, 31, 13, 0, tz=event_tz)
    proposals = _get_scheduled_proposals(filter_obj, override_user)
    upcoming = [_convert_time_to_str(p) for p in proposals if p["end_date"] > now]

    upcoming = sorted(upcoming, key=lambda p: p["start_date"])

    limit = filter_obj.get("limit", default=2, type=int)

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

    ical_sources = CalendarSource.query.filter_by(enabled=True, published=True)
    ical_source_names = [
        (v.mapobj.name, "ical", v.priority)
        for v in ical_sources
        if v.mapobj and v.events
    ]

    res = []
    seen_names = []
    for venue in main_venue_names + ical_source_names:
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

    res = sorted(res, key=lambda v: (v["source"] != "ical", v["order"]), reverse=True)
    return res
