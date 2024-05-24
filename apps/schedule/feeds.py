import json
from datetime import timedelta
from icalendar import Calendar, Event
from flask import request, abort, current_app as app, Response
from flask_cors import cross_origin
from flask_login import current_user
from math import ceil

from main import external_url
from models import event_year, event_start, event_end
from models.user import User
from models.cfp import Proposal

from ..common import feature_flag, feature_enabled, json_response
from .schedule_xml import export_frab
from .historic import feed_historic
from .data import (
    _get_scheduled_proposals,
    _get_proposal_dict,
    _convert_time_to_str,
    _get_upcoming,
)
from . import event_tz, schedule


def _format_event_description(event):
    description = event["description"] if event["description"] else ""
    if event["type"] in ["workshop", "youthworkshop"]:
        description += "\n\nAttending this workshop will cost: " + event["cost"]
        description += "\nSuitable age range: " + event["age_range"]
        description += "\nAttendees should bring: " + event["equipment"]

    footer_block = []
    if event["link"]:
        footer_block.append(f'Link: {event["link"]}')
    if event["venue"]:
        venue_str = event["venue"]
        if event["map_link"]:
            venue_str = f'{venue_str} ({event["map_link"]})'
        footer_block.append(f'Venue: {venue_str}')
    if footer_block:
        description += '\n\n' + '\n'.join(footer_block)

    return description


@schedule.route("/schedule/<int:year>.json")
@cross_origin(methods=["GET"])
def schedule_json(year):
    if year != event_year():
        return feed_historic(year, "json")

    if not feature_enabled('SCHEDULE'):
        abort(404)

    schedule = [_convert_time_to_str(p) for p in _get_scheduled_proposals(request.args)]

    # NB this is JSON in a top-level array (security issue for low-end browsers)
    return Response(json.dumps(schedule), mimetype="application/json")


@schedule.route("/schedule/schedule-<int:year>.json") # TODO validate url with upstream
@cross_origin(methods=["GET"])
def schedule_json_schema(year):
    if year != event_year():
        return feed_historic(year, "json")

    if not feature_enabled('SCHEDULE'):
        abort(404)

    def duration_hhmm(duration_minutes):
        if not duration_minutes or duration_minutes < 1:
            return "00:00"
        return "{}:{}".format(
            int(duration_minutes/60),
            str(duration_minutes%60).zfill(2),
        )

    schedule = (
        Proposal.query.filter(
            Proposal.is_accepted,
            Proposal.scheduled_time.isnot(None),
            Proposal.scheduled_venue_id.isnot(None),
            Proposal.scheduled_duration.isnot(None),
        )
        .order_by(Proposal.scheduled_time)
        .all()
    )

    duration_days = ceil((event_end() - event_end()).total_seconds / 86400),

    rooms = [
        proposal.scheduled_venue.name
        for proposal in schedule
    ]

    schedule_json = {
        "version": "1.0-public",
        "conference": {
            "acronym": "emf{}".format(event_year()),
            "days": [],
            "daysCount": duration_days,
            "end": event_end().strftime("%Y-%m-%d"),
            "rooms": [
                {
                    "name": room,
                }
                for room in rooms
            ],
            "start": event_start().strftime("%Y-%m-%d"),
            "time_zone_name": event_tz,
            "timeslot_duration": "00:10",
            "title": "Electromagnetic Field {}".format(event_year()),
            "url": external_url("main"),
        },
    }

    for day in range(0, duration_days):
        day_dt = event_start() + timedelta(days=day)
        day_schedule = {
            "date": day_dt.strftime("%Y-%m-%d"),
            "day_end": (day_dt.replace(hour=3, minute=59, second=59) + timedelta(days=1)).isoformat(),
            "day_start": day_dt.replace(hour=4, minute=0, second=0).isoformat(),
            "index": day,
            "rooms": {},
        }
        for room in rooms:
            day_schedule["rooms"][room] = []
            for proposal in schedule:
                if proposal.scheduled_venue.name != room:
                    # TODO find a better way to do that
                    continue
                links = {
                    proposal.c3voc_url,
                    proposal.youtube_url,
                    proposal.thumbnail_url,
                    proposal.map_link,
                }
                links.discard(None)
                links.discard("")
                day_schedule["rooms"][room].append({
                    "abstract": None, # The proposal model does not implement abstracts
                    "attachments": [],
                    "date": event_tz.localize(proposal.start_date).isoformat(),
                    "description": proposal.description,
                    "do_not_record": False if proposal.may_record else True,
                    "duration": duration_hhmm(proposal.duration_minutes),
                    "guid": None,
                    "id": proposal.id,
                    # This assumes there will never be a non-english talk,
                    # which is probably fine for a conference in the UK.
                    "language": "en",
                    "links": sorted(links),
                    "persons": [
                        {
                            "name": name.strip(),
                            "public_name": name.strip(),
                        }
                        for name in (proposal.published_names or proposal.user.name).split(",")
                    ],
                    "recording_license": "CC BY-SA 3.0",
                    "room": room,
                    "slug": "emf{}-{}-{}".format(
                        event_year(),
                        proposal.id,
                        proposal.slug,
                    ),
                    "start": event_tz.localize(proposal.start_date).strftime("%H:%M"),
                    "subtitle": None,
                    "title": proposal.display_title,
                    "track": None, # TODO does emf have tracks?
                    "type": proposal.type,
                    "url": external_url(
                        ".item",
                        year=event_year(),
                        proposal_id=proposal.id,
                        slug=proposal.slug,
                    ),
                })
        schedule_json["conference"]["days"].append(day_schedule)

    return Response(json.dumps({
        "schedule": schedule_json,
        "$schema": "https://c3voc.de/schedule/schema.json",
        "generator": {
            "name": "emfcamp-website",
            "url": "https://github.com/emfcamp/Website",
        },
    }), mimetype="application/json")


@schedule.route("/schedule/<int:year>.frab")
def schedule_frab(year):
    if year != event_year():
        return feed_historic(year, "frab")

    if not feature_enabled('SCHEDULE'):
        abort(404)

    schedule = (
        Proposal.query.filter(
            Proposal.is_accepted,
            Proposal.scheduled_time.isnot(None),
            Proposal.scheduled_venue_id.isnot(None),
            Proposal.scheduled_duration.isnot(None),
        )
        .order_by(Proposal.scheduled_time)
        .all()
    )

    schedule = [_get_proposal_dict(p, []) for p in schedule]

    frab = export_frab(schedule)

    return Response(frab, mimetype="application/xml")


@schedule.route("/schedule/<int:year>.ical")
@schedule.route("/schedule/<int:year>.ics")
def schedule_ical(year):
    if year != event_year():
        return feed_historic(year, "ics")

    if not feature_enabled('SCHEDULE'):
        abort(404)

    schedule = _get_scheduled_proposals(request.args)
    title = "EMF {}".format(event_year())

    cal = Calendar()
    cal.add("summary", title)
    cal.add("X-WR-CALNAME", title)
    cal.add("X-WR-CALDESC", title)
    cal.add("version", "2.0")

    for event in schedule:
        cal_event = Event()
        cal_event.add("uid", "%s-%s" % (year, event["id"]))
        cal_event.add("summary", event["title"])
        cal_event.add("description", _format_event_description(event))
        cal_event.add("location", event["venue"])
        cal_event.add("dtstart", event["start_date"])
        cal_event.add("dtend", event["end_date"])
        cal.add_component(cal_event)

    return Response(cal.to_ical(), mimetype="text/calendar")


@schedule.route("/favourites.json")
@feature_flag("LINE_UP")
def favourites_json():
    code = request.args.get("token", None)
    user = None
    if code:
        user = User.get_by_api_token(app.config.get("SECRET_KEY"), str(code))
    if not current_user.is_anonymous:
        user = current_user
    if not user:
        abort(404)

    schedule = [
        _convert_time_to_str(p)
        for p in _get_scheduled_proposals(request.args, override_user=user)
        if p["is_fave"]
    ]

    # NB this is JSON in a top-level array (security issue for low-end browsers)
    return Response(json.dumps(schedule), mimetype="application/json")


@schedule.route("/favourites.ical")
@schedule.route("/favourites.ics")
@feature_flag("LINE_UP")
def favourites_ical():
    code = request.args.get("token", None)
    user = None
    if code:
        user = User.get_by_api_token(app.config.get("SECRET_KEY"), str(code))
    if not current_user.is_anonymous:
        user = current_user
    if not user:
        abort(404)

    schedule = _get_scheduled_proposals(request.args, override_user=user)
    title = "EMF {} Favourites for {}".format(event_year(), user.name)

    cal = Calendar()
    cal.add("summary", title)
    cal.add("X-WR-CALNAME", title)
    cal.add("X-WR-CALDESC", title)
    cal.add("version", "2.0")

    for event in schedule:
        if not event["is_fave"]:
            continue
        cal_event = Event()
        cal_event.add("uid", "%s-%s" % (event_year(), event["id"]))
        cal_event.add("summary", event["title"])
        cal_event.add("description", _format_event_description(event))
        cal_event.add("location", event["venue"])
        cal_event.add("dtstart", event["start_date"])
        cal_event.add("dtend", event["end_date"])
        cal.add_component(cal_event)

    return Response(cal.to_ical(), mimetype="text/calendar")


@schedule.route("/schedule/now-and-next.json")
def now_and_next_json():
    return Response(
        json.dumps(_get_upcoming(request.args)), mimetype="application/json"
    )


@schedule.route("/schedule/<int:year>/<int:proposal_id>.json")
@schedule.route("/schedule/<int:year>/<int:proposal_id>-<slug>.json")
@json_response
@feature_flag("LINE_UP")
def item_json(year, proposal_id, slug=None):
    if year != event_year():
        abort(404)
    proposal = Proposal.query.get_or_404(proposal_id)
    if not proposal.is_accepted:
        abort(404)

    if not current_user.is_anonymous:
        favourites_ids = [f.id for f in current_user.favourites]
    else:
        favourites_ids = []

    data = _get_proposal_dict(proposal, favourites_ids)

    data["start_date"] = data["start_date"].strftime("%Y-%m-%d %H:%M:%S")
    data["end_date"] = data["end_date"].strftime("%Y-%m-%d %H:%M:%S")
    # Remove unnecessary data for now
    del data["link"]
    del data["source"]
    del data["id"]

    return data
