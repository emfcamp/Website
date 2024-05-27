import json
from icalendar import Calendar, Event
from flask import request, abort, current_app as app, Response
from flask_cors import cross_origin
from flask_login import current_user

from models import event_year
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
from . import schedule


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


@schedule.route("/now-and-next.json")
@schedule.route("/upcoming.json")
def upcoming():
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
