"""Utils to format schedule in the de facto standard Frab XML format.

Frab XML is consumed by a number of external tools such as C3VOC.
"""

from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from lxml import etree
from lxml.etree import _Element as Element

from apps.schedule.data import ScheduleItemDict
from main import external_url
from models import event_end, event_start, event_year

from . import event_tz


def get_duration(start_time: datetime, end_time: datetime) -> str:
    # str(timedelta) creates e.g. hrs:min:sec...
    duration = (end_time - start_time).total_seconds() / 60
    hours = int(duration // 60)
    minutes = int(duration % 60)
    if hours < 24:
        return f"{hours:d}:{minutes:02d}"
    days = int(hours // 24)
    hours = int(hours % 24)
    return f"{days:d}:{hours:02d}:{minutes:02d}"


def get_day_start_end(dt: datetime, start_time: time = time(4, 0)) -> tuple[datetime, datetime]:
    # A day changeover of 4am allows us to have late events.
    # All in local time because that's what people deal in.
    start_date = dt.date()
    if dt.time() < start_time:
        start_date -= timedelta(days=1)

    end_date = start_date + timedelta(days=1)

    start_dt = datetime.combine(start_date, start_time)
    end_dt = datetime.combine(end_date, start_time)

    start_dt = event_tz.localize(start_dt)
    end_dt = event_tz.localize(end_dt)

    return start_dt, end_dt


def _add_sub_with_text(parent: Element, tag: str, text: str, **extra: str) -> Element:
    node = etree.SubElement(parent, tag, None, None, **extra)
    node.text = text
    return node


def make_root() -> Element:
    root = etree.Element("schedule")

    _add_sub_with_text(root, "version", "1.0-public")

    conference = etree.SubElement(root, "conference")

    _add_sub_with_text(conference, "title", f"Electromagnetic Field {event_year()}")
    _add_sub_with_text(conference, "acronym", f"emf{event_year()}")
    _add_sub_with_text(conference, "start", event_start().strftime("%Y-%m-%d"))
    _add_sub_with_text(conference, "end", event_end().strftime("%Y-%m-%d"))
    _add_sub_with_text(conference, "days", "3")
    _add_sub_with_text(conference, "timeslot_duration", "00:10")

    return root


def add_day(root: Element, index: int, start: datetime, end: datetime) -> Element:
    return etree.SubElement(
        root,
        "day",
        index=str(index),
        date=start.strftime("%Y-%m-%d"),
        start=start.isoformat(),
        end=end.isoformat(),
    )


def add_room(day: Element, name: str) -> Element:
    return etree.SubElement(day, "room", name=name)


def add_event(room: Element, room_name: str, flat_sid: ScheduleItemDict) -> Element:
    event_guid_key = f"emf{event_year()}-{flat_sid['id']}-{flat_sid['occurrences'][0]['occurrence_num']}"
    event = etree.SubElement(
        room, "event", id=str(flat_sid["id"]), guid=str(uuid5(NAMESPACE_URL, event_guid_key))
    )

    # This is a silly schema
    _add_sub_with_text(event, "room", room_name)
    _add_sub_with_text(event, "title", flat_sid["title"])

    _add_sub_with_text(event, "type", flat_sid["type"])
    # infobeamer frab scheduler can color by "track"
    _add_sub_with_text(event, "track", flat_sid["type"])

    _add_sub_with_text(event, "date", flat_sid["occurrences"][0]["start_date"].isoformat())

    # FIXME: should we actually link to the occurrence?
    url: str = external_url(
        "schedule.item", year=event_year(), schedule_item_id=flat_sid["id"], slug=flat_sid["slug"]
    )
    _add_sub_with_text(event, "url", url)

    _add_sub_with_text(event, "start", flat_sid["occurrences"][0]["start_date"].strftime("%H:%M"))

    duration = get_duration(flat_sid["occurrences"][0]["start_date"], flat_sid["occurrences"][0]["end_date"])
    _add_sub_with_text(event, "duration", duration)

    _add_sub_with_text(event, "abstract", flat_sid["description"])
    _add_sub_with_text(event, "description", "")

    slug = "emf{}-{}-{}-{}".format(
        event_year(), flat_sid["id"], flat_sid["slug"], flat_sid["occurrences"][0]["occurrence_num"]
    )
    _add_sub_with_text(event, "slug", slug)

    _add_sub_with_text(event, "subtitle", "")

    add_persons(event, flat_sid)
    add_recording(event, flat_sid)

    return event


def add_persons(event: Element, flat_sid: ScheduleItemDict) -> Element:
    persons = etree.SubElement(event, "persons")

    # FIXME: do we need to split up names somehow?
    _add_sub_with_text(persons, "person", flat_sid["names"], id="1")

    return persons


def add_recording(event: Element, flat_sid: ScheduleItemDict) -> Element:
    recording = etree.SubElement(event, "recording")

    _add_sub_with_text(recording, "license", "CC BY-SA 4.0")
    _add_sub_with_text(
        recording,
        "optout",
        "false" if flat_sid["occurrences"][0]["video_privacy"] == "public" else "true",
    )
    if "ccc_url" in flat_sid["occurrences"][0]:
        _add_sub_with_text(recording, "url", flat_sid["occurrences"][0]["ccc_url"])
    elif "youtube_url" in flat_sid["occurrences"][0]:
        _add_sub_with_text(recording, "url", flat_sid["occurrences"][0]["youtube_url"])

    return recording


def export_frab(flat_sids: Sequence[ScheduleItemDict]) -> bytes:
    root: Element = make_root()
    days_dict: dict[str, dict[str, Any]] = {}
    index: int = 0

    for flat_sid in flat_sids:
        day_start, day_end = get_day_start_end(flat_sid["occurrences"][0]["start_date"])
        day_key = day_start.strftime("%Y-%m-%d")
        venue_key = flat_sid["occurrences"][0]["venue"]

        if day_key not in days_dict:
            index += 1
            node = add_day(root, index, day_start, day_end)
            days_dict[day_key] = {"node": node, "rooms": {}}

        day = days_dict[day_key]

        if venue_key not in day["rooms"]:
            day["rooms"][venue_key] = add_room(day["node"], venue_key)

        add_event(day["rooms"][venue_key], venue_key, flat_sid)

    return etree.tostring(root)
