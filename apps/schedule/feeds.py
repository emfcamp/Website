import json
from datetime import timedelta

from dateutil.parser import parse as parse_date
from flask import Response, abort, redirect, request, url_for
from flask import current_app as app
from flask.typing import ResponseReturnValue
from flask_cors import cross_origin
from flask_login import current_user
from icalendar import Calendar, Event
from sqlalchemy import select

from main import db, external_url, get_or_404
from models.content import Occurrence, ScheduleItem
from models.user import User

from ..common import feature_enabled, feature_flag, json_response
from ..config import config
from . import event_tz, schedule
from .data import (
    ScheduleFilter,
    ScheduleItemDict,
    _fix_up_times_horribly,
    get_schedule_item_dict_full,
    get_schedule_item_dicts_flat,
    get_schedule_items,
    get_upcoming,
)
from .frab_exporter import FrabExporterFilter, FrabJsonExporter, FrabXmlExporter
from .historic import feed_historic


def _format_event_description(flat_sid: ScheduleItemDict) -> str:
    description = flat_sid["description"] if flat_sid["description"] else ""
    if flat_sid["type"] in ["workshop", "familyworkshop"]:
        # Safe assertions because we add them in _get_schedule_item_dict
        assert "cost" in flat_sid
        assert "equipment" in flat_sid
        assert "age_range" in flat_sid
        description += "\n\nAttending this workshop will cost: " + flat_sid["cost"]
        description += "\nSuitable age range: " + flat_sid["age_range"]
        description += "\nAttendees should bring: " + flat_sid["equipment"]

    footer_block = []
    if flat_sid["link"]:
        footer_block.append(f"Link: {flat_sid['link']}")
    if flat_sid["occurrences"][0]["venue"]:
        venue_str = flat_sid["occurrences"][0]["venue"]
        if flat_sid["occurrences"][0]["map_link"]:
            venue_str = f"{venue_str} ({flat_sid['occurrences'][0]['map_link']})"
        footer_block.append(f"Venue: {venue_str}")
    if footer_block:
        description += "\n\n" + "\n".join(footer_block)

    return description


@schedule.route("/schedule/<int:year>.json")
@cross_origin(methods=["GET"])
def schedule_json(year: int) -> ResponseReturnValue:
    if year != config.event_year:
        return feed_historic(year, "json")

    if not feature_enabled("LINE_UP"):
        abort(404)

    filter = ScheduleFilter.from_request()
    schedule_items = get_schedule_items(filter)
    full_sids = [get_schedule_item_dict_full(filter, si) for si in schedule_items]

    if not feature_enabled("SCHEDULE"):
        full_sids = [sid | {"occurrences": []} for sid in full_sids]

    _fix_up_times_horribly(full_sids)

    return Response(json.dumps(full_sids), mimetype="application/json")


@schedule.route("/schedule/<int:year>.frab")
def schedule_frab(year: int) -> ResponseReturnValue:
    if year != config.event_year:
        return feed_historic(year, "frab")

    return redirect(url_for("schedule.schedule_frab_xml", year=year))


@schedule.route("/schedule/<int:year>.frab.xml")
def schedule_frab_xml(year):
    if year != config.event_year:
        return feed_historic(year, "frab")

    if not feature_enabled("SCHEDULE"):
        abort(404)

    # FIXME: the only real difference between this and get_schedule_items is the ordering
    # Should we move the order_by into there?
    schedule_items = list(
        db.session.scalars(
            select(ScheduleItem)
            .join(Occurrence)
            .where(
                ScheduleItem.state == "published",
                ScheduleItem.occurrences.any(
                    Occurrence.scheduled_time.isnot(None),
                ),
            )
            .order_by(Occurrence.scheduled_time)
        ).unique()
    )

    filter = FrabExporterFilter.from_request()

    exporter = FrabXmlExporter(filter, schedule_items)
    frab = exporter.run()

    return Response(frab, mimetype="application/xml")


@schedule.route("/schedule/<int:year>.frab.json")
def schedule_frab_json(year):
    if year != config.event_year:
        return feed_historic(year, "frab_json")

    if not feature_enabled("SCHEDULE"):
        abort(404)

    schedule_items = list(
        db.session.scalars(
            select(ScheduleItem)
            .join(Occurrence)
            .where(
                ScheduleItem.state == "published",
                ScheduleItem.occurrences.any(
                    Occurrence.scheduled_time.isnot(None),
                ),
            )
            .order_by(Occurrence.scheduled_time)
        ).unique()
    )

    filter = FrabExporterFilter.from_request()

    exporter = FrabJsonExporter(
        filter, schedule_items, external_url("schedule.schedule_frab_json", year=year)
    )
    frab = exporter.run()

    return Response(json.dumps(frab, indent=4), mimetype="application/json")


@schedule.route("/schedule/<int:year>.ical")
@schedule.route("/schedule/<int:year>.ics")
def schedule_ical(year: int) -> ResponseReturnValue:
    if year != config.event_year:
        return feed_historic(year, "ics")

    if not feature_enabled("SCHEDULE"):
        abort(404)

    filter = ScheduleFilter.from_request()
    schedule_items = get_schedule_items(filter)
    flat_sids = [flat_sid for si in schedule_items for flat_sid in get_schedule_item_dicts_flat(filter, si)]
    title = f"EMF {config.event_year}"

    cal = Calendar()
    cal.add("summary", title)
    cal.add("X-WR-CALNAME", title)
    cal.add("X-WR-CALDESC", title)
    cal.add("version", "2.0")

    for flat_sid in flat_sids:
        cal_event = Event()
        occurrence = flat_sid["occurrences"][0]
        cal_event.add("uid", f"{year}-content-{flat_sid['id']}-{occurrence['occurrence_num']}")
        cal_event.add("summary", flat_sid["title"])
        cal_event.add("description", _format_event_description(flat_sid))
        cal_event.add("location", occurrence["venue"])
        cal_event.add("dtstart", occurrence["start_date"])
        cal_event.add("dtend", occurrence["end_date"])
        cal.add_component(cal_event)

    return Response(cal.to_ical(), mimetype="text/calendar")


@schedule.route("/favourites.json")
@feature_flag("LINE_UP")
def favourites_json() -> ResponseReturnValue:
    token = request.args.get("token", None)
    if token:
        # Let token take precedence, and tell the user if it's invalid
        user = User.get_by_api_token(app.config["SECRET_KEY"], token)
        if user is None:
            abort(401)
    elif current_user.is_anonymous:
        abort(404)
    else:
        user = current_user

    filter = ScheduleFilter(
        venues=[],
        is_favourite=True,
        user=user,
    )

    schedule_items = get_schedule_items(filter)
    full_sids = [get_schedule_item_dict_full(filter, sid) for sid in schedule_items]

    _fix_up_times_horribly(full_sids)

    return Response(json.dumps(full_sids), mimetype="application/json")


@schedule.route("/favourites.ical")
@schedule.route("/favourites.ics")
@feature_flag("LINE_UP")
def favourites_ical() -> ResponseReturnValue:
    token = request.args.get("token", None)
    if token:
        # Let token take precedence, and tell the user if it's invalid
        user = User.get_by_api_token(app.config["SECRET_KEY"], token)
        if user is None:
            abort(401)
    elif current_user.is_anonymous:
        abort(404)
    else:
        user = current_user

    if feature_enabled("SCHEDULE"):
        filter = ScheduleFilter(
            venues=[],
            is_favourite=True,
            user=user,
        )
        assert filter.user is not None

        schedule_items = get_schedule_items(filter)
        flat_sids = [
            flat_sid for si in schedule_items for flat_sid in get_schedule_item_dicts_flat(filter, si)
        ]
    else:
        flat_sids = []

    title = f"EMF {config.event_year} Favourites for {user.name}"

    cal = Calendar()
    cal.add("summary", title)
    cal.add("X-WR-CALNAME", title)
    cal.add("X-WR-CALDESC", title)
    cal.add("version", "2.0")

    event_address = app.config["EVENT_ADDRESS"]

    fixed_events = {
        "Gates open": app.config["GATE_OPENED"],
        "Site closes": app.config["GATE_CLOSED"],
    }

    for i, fev in enumerate(fixed_events.items()):
        name, start_s = fev
        start_date = event_tz.localize(parse_date(start_s))
        cal_event = Event()
        cal_event.add("uid", f"{config.event_year}-fixed-{i}")
        cal_event.add("summary", name)
        cal_event.add("location", event_address)
        cal_event.add("dtstart", start_date)
        cal_event.add("dtend", start_date + timedelta(hours=1))
        cal.add_component(cal_event)

    for flat_sid in flat_sids:
        cal_event = Event()
        occurrence = flat_sid["occurrences"][0]
        cal_event.add("uid", f"{config.event_year}-content-{flat_sid['id']}-{occurrence['occurrence_num']}")
        cal_event.add("summary", flat_sid["title"])
        cal_event.add("description", _format_event_description(flat_sid))
        cal_event.add("location", occurrence["venue"])
        cal_event.add("dtstart", occurrence["start_date"])
        cal_event.add("dtend", occurrence["end_date"])
        cal.add_component(cal_event)

    return Response(cal.to_ical(), mimetype="text/calendar")


@schedule.route("/schedule/now-and-next.json")
def now_and_next_json() -> ResponseReturnValue:
    filter = ScheduleFilter.from_request()
    per_venue_limit = int(request.args.get("limit", 2))
    venue_slug_sids = get_upcoming(filter, per_venue_limit)
    return Response(json.dumps(venue_slug_sids), mimetype="application/json")


@schedule.route("/schedule/<int:year>/<int:schedule_item_id>.json")
@schedule.route("/schedule/<int:year>/<int:schedule_item_id>-<slug>.json")
@json_response
@feature_flag("LINE_UP")
def item_json(year: int, schedule_item_id: int, slug: str | None = None) -> ResponseReturnValue:
    if year != config.event_year:
        abort(404)
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)

    # TODO: redirect to the correct slug?

    filter = ScheduleFilter(
        venues=[],
        is_favourite=False,
        user=(current_user.is_authenticated and current_user) or None,
    )

    sid = get_schedule_item_dict_full(filter, schedule_item)

    # FIXME: do we really need to do this?
    for od in sid["occurrences"]:
        od["start_date"] = od["start_date"].strftime("%Y-%m-%d %H:%M:%S")  # type: ignore
        od["end_date"] = od["end_date"].strftime("%Y-%m-%d %H:%M:%S")  # type: ignore

    # Remove unnecessary data for now
    del sid["link"]  # type: ignore
    del sid["id"]  # type: ignore

    return sid
