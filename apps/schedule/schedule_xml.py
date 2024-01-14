""" Utils to format schedule in the de facto standard Frab XML format.

    Frab XML is consumed by a number of external tools such as C3VOC.
"""
from uuid import uuid5, NAMESPACE_URL
from datetime import time, datetime, timedelta
from lxml import etree

from main import external_url
from models import event_year, event_start, event_end

from . import event_tz


def get_duration(start_time, end_time):
    # str(timedelta) creates e.g. hrs:min:sec...
    duration = (end_time - start_time).total_seconds() / 60
    hours = int(duration // 60)
    minutes = int(duration % 60)
    return "{0:01d}:{1:02d}".format(hours, minutes)


def get_day_start_end(dt, start_time=time(4, 0)):
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


def _add_sub_with_text(parent, element, text, **extra):
    node = etree.SubElement(parent, element, **extra)
    node.text = text
    return node


def make_root():
    root = etree.Element("schedule")

    _add_sub_with_text(root, "version", "1.0-public")

    conference = etree.SubElement(root, "conference")

    _add_sub_with_text(
        conference, "title", "Electromagnetic Field {}".format(event_year())
    )
    _add_sub_with_text(conference, "acronym", "emf{}".format(event_year()))
    _add_sub_with_text(conference, "start", event_start().strftime("%Y-%m-%d"))
    _add_sub_with_text(conference, "end", event_end().strftime("%Y-%m-%d"))
    _add_sub_with_text(conference, "days", "3")
    _add_sub_with_text(conference, "timeslot_duration", "00:10")

    return root


def add_day(root, index, start, end):
    return etree.SubElement(
        root,
        "day",
        index=str(index),
        date=start.strftime("%Y-%m-%d"),
        start=start.isoformat(),
        end=end.isoformat(),
    )


def add_room(day, name):
    return etree.SubElement(day, "room", name=name)


def add_event(room, event):
    url = external_url(
        "schedule.item", year=event_year(), proposal_id=event["id"], slug=event["slug"]
    )

    event_node = etree.SubElement(
        room, "event", id=str(event["id"]), guid=str(uuid5(NAMESPACE_URL, url))
    )

    _add_sub_with_text(event_node, "room", room.attrib["name"])
    _add_sub_with_text(event_node, "title", event["title"])
    _add_sub_with_text(event_node, "type", event.get("type", "talk"))
    _add_sub_with_text(event_node, "date", event["start_date"].isoformat())

    # Start time
    _add_sub_with_text(event_node, "start", event["start_date"].strftime("%H:%M"))

    duration = get_duration(event["start_date"], event["end_date"])
    _add_sub_with_text(event_node, "duration", duration)

    _add_sub_with_text(event_node, "abstract", event["description"])
    _add_sub_with_text(event_node, "description", "")

    _add_sub_with_text(
        event_node,
        "slug",
        "emf%s-%s-%s" % (event_year(), event["id"], event["slug"]),
    )

    _add_sub_with_text(event_node, "subtitle", "")
    _add_sub_with_text(event_node, "track", "")

    add_persons(event_node, event)
    add_recording(event_node, event)


def add_persons(event_node, event):

    persons_node = etree.SubElement(event_node, "persons")

    _add_sub_with_text(
        persons_node, "person", event["speaker"], id=str(event["user_id"])
    )


def add_recording(event_node, event):
    video = event.get("video", {})

    recording_node = etree.SubElement(event_node, "recording")

    _add_sub_with_text(recording_node, "license", "CC BY-SA 3.0")
    _add_sub_with_text(
        recording_node, "optout", "false" if event.get("may_record") else "true"
    )
    if "ccc" in video:
        _add_sub_with_text(recording_node, "url", video["ccc"])
    elif "youtube" in video:
        _add_sub_with_text(recording_node, "url", video["youtube"])


def export_frab(schedule):
    root = make_root()
    days_dict = {}
    index = 0

    for event in schedule:
        day_start, day_end = get_day_start_end(event["start_date"])
        day_key = day_start.strftime("%Y-%m-%d")
        venue_key = event["venue"]

        if day_key not in days_dict:
            index += 1
            node = add_day(root, index, day_start, day_end)
            days_dict[day_key] = {"node": node, "rooms": {}}

        day = days_dict[day_key]

        if venue_key not in day["rooms"]:
            day["rooms"][venue_key] = add_room(day["node"], venue_key)

        add_event(day["rooms"][venue_key], event)

    return etree.tostring(root)
