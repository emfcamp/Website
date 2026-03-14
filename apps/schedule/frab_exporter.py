from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from functools import cached_property
from hashlib import md5
from uuid import NAMESPACE_URL, uuid5

from flask import request
from lxml import etree
from lxml.etree import _Element as Element

from main import external_url
from models import event_end, event_start, event_year
from models.cfp import SCHEDULE_ITEM_INFOS, ScheduleItem, Venue

from . import event_tz
from .data import ScheduleFilter, ScheduleItemDict, _get_occurrence_dict, _get_schedule_item_dict

# Default licence for recordings
LICENCE = "CC BY-SA 4.0"
VERSION = "1.0-public"

TRACK_COLOURS = {
    type_info.type: f"#{md5(type_info.human_type.encode('utf-8')).hexdigest()[:6]}"
    for type_info in SCHEDULE_ITEM_INFOS.values()
}


@dataclass
class FrabExporterFilter:
    official_venues_only: bool = False
    village_id: int | None = None
    venue_ids: Sequence[int] = field(default_factory=list)

    @classmethod
    def from_request(cls):
        official_venues_only = request.args.get("official_venues_only") in {"true", "yes", "1"}
        venue_ids_raw = request.args.get("venue_ids", "").split(",")
        venue_ids = [int(id.strip()) for id in venue_ids_raw if id.strip()]
        village_id_raw = request.args.get("village_id")
        village_id = int(village_id_raw) if village_id_raw else None
        return FrabExporterFilter(
            official_venues_only=official_venues_only,
            village_id=village_id,
            venue_ids=venue_ids,
        )


class FrabExporter:
    def __init__(self, filter: FrabExporterFilter, schedule_items: Sequence[ScheduleItem]):
        self.schedule_items = schedule_items
        self.filter = filter

    def format_duration(self, start_time: datetime, end_time: datetime) -> str:
        duration = (end_time - start_time).total_seconds() / 60
        hours = int(duration // 60)
        minutes = int(duration % 60)
        if hours < 24:
            return f"{hours:d}:{minutes:02d}"
        days = int(hours // 24)
        hours = int(hours % 24)
        return f"{days:d}:{hours:02d}:{minutes:02d}"

    def get_day_start_end(self, dt: datetime, start_time: time = time(4, 0)) -> tuple[datetime, datetime]:
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

    @cached_property
    def schedule(self):
        # This is basically a reimplementation of get_schedule_item_dicts_flat
        # TODO: it might be better to use the ScheduleItem/Occurrences directly
        if not self.schedule_items:
            return []

        # Empty filter
        filter = ScheduleFilter()

        data = {}
        index = 0
        for schedule_item in self.schedule_items:
            sid = _get_schedule_item_dict(filter, schedule_item)
            for occurrence in schedule_item.occurrences:
                if occurrence.state != "scheduled":
                    continue

                # Safe assertion due to check that state == "scheduled"
                assert occurrence.scheduled_venue is not None

                if self.filter.official_venues_only and occurrence.scheduled_venue.allows_attendee_content:
                    continue

                if self.filter.village_id and occurrence.scheduled_venue.village_id != self.filter.village_id:
                    continue

                if self.filter.venue_ids and occurrence.scheduled_venue.id not in self.filter.venue_ids:
                    continue

                od = _get_occurrence_dict(filter, occurrence)
                # TODO: maybe we should type these differently
                flat_sid = sid.copy()
                flat_sid["occurrences"] = [od]

                day_start, day_end = self.get_day_start_end(od["start_date"])
                day_key = day_start.strftime("%Y-%m-%d")
                venue_key = occurrence.scheduled_venue.name

                if day_key not in data:
                    data[day_key] = {
                        "index": index,
                        "start": day_start,
                        "end": day_end,
                        "rooms": {},
                    }
                    index += 1

                day = data[day_key]
                if venue_key not in day["rooms"]:
                    day["rooms"][venue_key] = {
                        "id": occurrence.scheduled_venue.id,
                        "name": occurrence.scheduled_venue.name,
                        "talks": [],
                    }

                day["rooms"][venue_key]["talks"].append(flat_sid)

        for day in data.values():
            day["rooms"] = sorted(
                day["rooms"].values(),
                key=lambda room: room["id"],
            )
        return data.values()


class FrabJsonExporter(FrabExporter):
    def __init__(self, filter: FrabExporterFilter, schedule_items: Sequence[ScheduleItem], url: str):
        super().__init__(filter, schedule_items)
        self.url = url

    @cached_property
    def venues(self):
        venues = Venue.query.order_by(Venue.name).all()
        result = []
        for venue in venues:
            if self.filter.official_venues_only and venue.allows_attendee_content:
                continue

            if self.filter.village_id and venue.village_id != self.filter.village_id:
                continue

            if self.filter.venue_ids and venue.id not in self.filter.venue_ids:
                continue

            result.append(venue)
        return result

    def run(self):
        return {
            "$schema": "https://c3voc.de/schedule/schema.json",
            "schedule": {
                "url": self.url,
                "version": VERSION,
                "base_url": external_url("base.main"),
                "conference": {
                    "acronym": f"emf{event_year()}",
                    "title": f"Electromagnetic Field {event_year()}",
                    "start": event_start().strftime("%Y-%m-%d"),
                    "end": event_end().strftime("%Y-%m-%d"),
                    "daysCount": 3,
                    "timeslot_duration": "00:10",
                    "time_zone_name": event_tz.zone,
                    "rooms": [
                        {
                            "name": venue.name,
                            "capacity": venue.capacity,
                        }
                        for venue in self.venues
                    ],
                    "tracks": [
                        {
                            "name": type_info.human_type,
                            "slug": type_info.type,
                            "color": TRACK_COLOURS[type_info.type],
                        }
                        for type_info in SCHEDULE_ITEM_INFOS.values()
                    ],
                    "days": [
                        {
                            "index": day["index"],
                            "date": day["start"].strftime("%Y-%m-%d"),
                            "day_start": day["start"].isoformat(),
                            "day_end": day["end"].isoformat(),
                            "rooms": {
                                room["name"]: [
                                    {
                                        "guid": str(uuid5(NAMESPACE_URL, flat_sid["link"])),
                                        "id": flat_sid["id"],
                                        "date": flat_sid["occurrences"][0]["start_date"].isoformat(),
                                        "start": flat_sid["occurrences"][0]["start_date"].strftime("%H:%M"),
                                        "duration": self.format_duration(
                                            flat_sid["occurrences"][0]["start_date"],
                                            flat_sid["occurrences"][0]["end_date"],
                                        ),
                                        "room": room["name"],
                                        "slug": "emf{}-{}-{}".format(
                                            event_year(), flat_sid["id"], flat_sid["slug"]
                                        ),
                                        "url": flat_sid["link"],
                                        "title": flat_sid["title"],
                                        "subtitle": "",
                                        "track": SCHEDULE_ITEM_INFOS[flat_sid["type"]].human_type,
                                        "type": flat_sid["type"],
                                        "language": "en",
                                        "abstract": flat_sid["description"],
                                        "description": "",
                                        "recording_license": LICENCE,
                                        "do_not_record": bool(
                                            flat_sid["occurrences"][0]["video_privacy"] != "public"
                                        ),
                                        "persons": [
                                            {
                                                "name": flat_sid["names"],
                                            }
                                        ],
                                        "links": [
                                            {
                                                "title": "ccc",
                                                "url": flat_sid["occurrences"][0]["ccc_url"],
                                                "type": "related",
                                            }
                                        ]
                                        if "ccc_url" in flat_sid
                                        else [
                                            {
                                                "title": "youtube",
                                                "url": flat_sid["occurrences"][0]["youtube_url"],
                                                "type": "related",
                                            }
                                        ]
                                        if "youtube" in flat_sid
                                        else [],
                                    }
                                    for flat_sid in room["talks"]
                                ]
                                for room in day["rooms"]
                            },
                        }
                        for day in self.schedule
                    ],
                },
            },
        }


class FrabXmlExporter(FrabExporter):
    def _add_sub_with_text(self, parent: Element, tag: str, text: str, **extra: str) -> Element:
        node = etree.SubElement(parent, tag, None, None, **extra)
        node.text = text
        return node

    def make_root(self) -> Element:
        root = etree.Element("schedule")

        self._add_sub_with_text(root, "version", VERSION)

        conference = etree.SubElement(root, "conference")

        self._add_sub_with_text(conference, "title", f"Electromagnetic Field {event_year()}")
        self._add_sub_with_text(conference, "acronym", f"emf{event_year()}")
        self._add_sub_with_text(conference, "start", event_start().strftime("%Y-%m-%d"))
        self._add_sub_with_text(conference, "end", event_end().strftime("%Y-%m-%d"))
        self._add_sub_with_text(conference, "days", "3")
        self._add_sub_with_text(conference, "timeslot_duration", "00:10")
        self._add_sub_with_text(conference, "time_zone_name", event_tz.zone)
        self._add_sub_with_text(conference, "url", external_url("base.main"))

        return root

    def add_day(self, root: Element, index: int, start: datetime, end: datetime) -> Element:
        return etree.SubElement(
            root,
            "day",
            index=str(index),
            date=start.strftime("%Y-%m-%d"),
            start=start.isoformat(),
            end=end.isoformat(),
        )

    def add_room(self, day: Element, name: str) -> Element:
        return etree.SubElement(day, "room", name=name)

    def add_event(self, room: Element, room_name: str, flat_sid: ScheduleItemDict) -> Element:
        event_guid_key = f"emf{event_year()}-{flat_sid['id']}-{flat_sid['occurrences'][0]['occurrence_num']}"
        event = etree.SubElement(
            room, "event", id=str(flat_sid["id"]), guid=str(uuid5(NAMESPACE_URL, event_guid_key))
        )

        # This is a silly schema
        self._add_sub_with_text(event, "room", room_name)
        self._add_sub_with_text(event, "title", flat_sid["title"])

        self._add_sub_with_text(event, "type", flat_sid["type"])
        # infobeamer frab scheduler can color by "track"
        self._add_sub_with_text(event, "track", SCHEDULE_ITEM_INFOS[flat_sid["type"]].human_type)

        self._add_sub_with_text(event, "date", flat_sid["occurrences"][0]["start_date"].isoformat())

        # FIXME: should we actually link to the occurrence?
        url: str = external_url(
            "schedule.item", year=event_year(), schedule_item_id=flat_sid["id"], slug=flat_sid["slug"]
        )
        self._add_sub_with_text(event, "url", url)

        self._add_sub_with_text(event, "start", flat_sid["occurrences"][0]["start_date"].strftime("%H:%M"))

        duration = self.format_duration(
            flat_sid["occurrences"][0]["start_date"], flat_sid["occurrences"][0]["end_date"]
        )
        self._add_sub_with_text(event, "duration", duration)

        self._add_sub_with_text(event, "abstract", flat_sid["description"])
        self._add_sub_with_text(event, "description", "")

        slug = "emf{}-{}-{}-{}".format(
            event_year(), flat_sid["id"], flat_sid["slug"], flat_sid["occurrences"][0]["occurrence_num"]
        )
        self._add_sub_with_text(event, "slug", slug)

        self._add_sub_with_text(event, "subtitle", "")

        self.add_persons(event, flat_sid)
        self.add_recording(event, flat_sid)

        return event

    def add_persons(self, event: Element, flat_sid: ScheduleItemDict) -> Element:
        persons = etree.SubElement(event, "persons")

        # FIXME: do we need to split up names somehow?
        self._add_sub_with_text(persons, "person", flat_sid["names"], id="1")

        return persons

    def add_recording(self, event: Element, flat_sid: ScheduleItemDict) -> Element:
        recording = etree.SubElement(event, "recording")
        self._add_sub_with_text(recording, "license", LICENCE)

        od = flat_sid["occurrences"][0]
        if od["video_privacy"] == "public":
            self._add_sub_with_text(recording, "optout", "false")
            if "ccc_url" in od:
                self._add_sub_with_text(recording, "url", od["ccc_url"])
            elif "youtube_url" in flat_sid["occurrences"][0]:
                self._add_sub_with_text(recording, "url", od["youtube_url"])

        else:
            self._add_sub_with_text(recording, "optout", "true")

        return recording

    def run(self) -> bytes:
        root: Element = self.make_root()

        for schedule_day in self.schedule:
            day = self.add_day(root, schedule_day["index"], schedule_day["start"], schedule_day["end"])

            for schedule_venue in schedule_day["rooms"]:
                room = self.add_room(day, schedule_venue["name"])

                for schedule_event in schedule_venue["talks"]:
                    self.add_event(room, schedule_venue["name"], schedule_event)

        return etree.tostring(root)
