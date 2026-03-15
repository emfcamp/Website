from datetime import datetime, time, timedelta
from functools import cached_property
from hashlib import md5
from uuid import NAMESPACE_URL, uuid5

from lxml import etree

from main import external_url
from models import event_end, event_start, event_year
from models.cfp import HUMAN_CFP_TYPES, Venue

from . import event_tz
from .data import _get_proposal_dict

LICENCE = "CC BY-SA 4.0"
VERSION = "1.0-public"

TRACK_COLOURS = {
    slug: f"#{md5(human_readable.encode('utf-8')).hexdigest()[:6]}"
    for slug, human_readable in HUMAN_CFP_TYPES.items()
}


class FrabExporter:
    def __init__(self, schedule, scheduled_content_only=False, village_id=None, venue_ids=None):
        self._schedule = schedule
        self._scheduled_content_only = scheduled_content_only
        self._village_id = village_id
        if venue_ids:
            self._venue_ids = [int(id.strip()) for id in venue_ids if id.strip()]
        else:
            self._venue_ids = []

    def format_duration(self, start_time: datetime, end_time: datetime) -> str:
        # str(timedelta) creates e.g. hrs:min:sec...
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
        if not self._schedule:
            return []
        data = {}
        index = 0
        for event in self._schedule:
            event_dict = _get_proposal_dict(event, [])
            day_start, day_end = self.get_day_start_end(event_dict["start_date"])
            day_key = day_start.strftime("%Y-%m-%d")
            venue_key = event.scheduled_venue.name

            if self._scheduled_content_only and not event.scheduled_venue.scheduled_content_only:
                continue

            if self._village_id and event.scheduled_venue.village_id != self._village_id:
                continue

            if self._venue_ids and event.scheduled_venue.id not in self._venue_ids:
                continue

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
                    "id": event.scheduled_venue.id,
                    "name": event.scheduled_venue.name,
                    "talks": [],
                }

            day["rooms"][venue_key]["talks"].append(event_dict)

        for day in data.values():
            day["rooms"] = sorted(
                day["rooms"].values(),
                key=lambda room: room["id"],
            )
        return data.values()


class FrabJsonExporter(FrabExporter):
    def __init__(self, schedule, url=None, scheduled_content_only=False, village_id=None, venue_ids=None):
        super().__init__(
            schedule,
            scheduled_content_only=scheduled_content_only,
            village_id=village_id,
            venue_ids=venue_ids,
        )
        self.url = url

    @cached_property
    def rooms(self):
        rooms = Venue.query.order_by(Venue.name).all()
        result = []
        for room in rooms:
            if self._scheduled_content_only and not room.scheduled_content_only:
                continue

            if self._village_id and room.village_id != self._village_id:
                continue

            if self._venue_ids and room.id not in self._venue_ids:
                continue

            result.append(room)
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
                            "name": room.name,
                            "capacity": room.capacity,
                            # TODO do we have an URL for listing the schedule in a specific room?
                            "guid": str(uuid5(NAMESPACE_URL, room.name)),
                        }
                        for room in self.rooms
                    ],
                    "tracks": [
                        {
                            "name": human_readable,
                            "slug": slug,
                            "color": TRACK_COLOURS[slug],
                        }
                        for slug, human_readable in sorted(HUMAN_CFP_TYPES.items())
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
                                        "guid": str(uuid5(NAMESPACE_URL, event["link"])),
                                        "id": event["id"],
                                        "date": event["start_date"].isoformat(),
                                        "start": event["start_date"].strftime("%H:%M"),
                                        "duration": self.format_duration(
                                            event["start_date"], event["end_date"]
                                        ),
                                        "room": room["name"],
                                        "slug": "emf{}-{}-{}".format(
                                            event_year(), event["id"], event["slug"]
                                        ),
                                        "url": event["link"],
                                        "title": event["title"],
                                        "subtitle": "",
                                        "track": HUMAN_CFP_TYPES[event["type"]],
                                        "type": event["type"],
                                        "language": "en",
                                        "abstract": event["description"],
                                        "description": "",
                                        "recording_license": LICENCE,
                                        "do_not_record": bool(event.get("video_privacy") != "public"),
                                        "persons": [
                                            {
                                                "name": event["speaker"],
                                            }
                                        ],
                                        "links": [
                                            {
                                                "title": "ccc",
                                                "url": event["video"]["ccc"],
                                                "type": "related",
                                            }
                                        ]
                                        if "ccc" in event.get("video")
                                        else [
                                            {
                                                "title": "youtube",
                                                "url": event["video"]["youtube"],
                                                "type": "related",
                                            }
                                        ]
                                        if "youtube" in event.get("video")
                                        else [],
                                    }
                                    for event in room["talks"]
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
    def _add_sub_with_text(self, parent, element, text, **extra):
        node = etree.SubElement(parent, element, **extra)
        node.text = text
        return node

    def make_root(self):
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

    def add_day(self, root, index, start, end):
        return etree.SubElement(
            root,
            "day",
            index=str(index),
            date=start.strftime("%Y-%m-%d"),
            start=start.isoformat(),
            end=end.isoformat(),
        )

    def add_room(self, day, name):
        return etree.SubElement(day, "room", name=name)

    def add_event(self, room, event):
        event_node = etree.SubElement(
            room, "event", id=str(event["id"]), guid=str(uuid5(NAMESPACE_URL, event["link"]))
        )

        self._add_sub_with_text(event_node, "room", room.attrib["name"])
        self._add_sub_with_text(event_node, "title", event["title"])

        event_type = event.get("type", "talk")
        self._add_sub_with_text(event_node, "type", event_type)
        # infobeamer frab scheduler can color by "track"
        self._add_sub_with_text(event_node, "track", HUMAN_CFP_TYPES[event_type])

        self._add_sub_with_text(event_node, "date", event["start_date"].isoformat())
        self._add_sub_with_text(event_node, "url", event["link"])

        # Start time
        self._add_sub_with_text(event_node, "start", event["start_date"].strftime("%H:%M"))

        duration = self.format_duration(event["start_date"], event["end_date"])
        self._add_sub_with_text(event_node, "duration", duration)

        self._add_sub_with_text(event_node, "abstract", event["description"])
        self._add_sub_with_text(event_node, "description", "")

        self._add_sub_with_text(
            event_node,
            "slug",
            "emf{}-{}-{}".format(event_year(), event["id"], event["slug"]),
        )

        self._add_sub_with_text(event_node, "subtitle", "")

        self.add_persons(event_node, event)
        self.add_recording(event_node, event)

    def add_persons(self, event_node, event):
        persons_node = etree.SubElement(event_node, "persons")
        self._add_sub_with_text(persons_node, "person", event["speaker"], id=str(event["user_id"]))

    def add_recording(self, event_node, event):
        recording_node = etree.SubElement(event_node, "recording")
        self._add_sub_with_text(recording_node, "license", LICENCE)

        if event.get("video_privacy") == "public":
            video = event.get("video", {})
            self._add_sub_with_text(recording_node, "optout", "false")
            if "ccc" in video:
                self._add_sub_with_text(recording_node, "url", video["ccc"])
            elif "youtube" in video:
                self._add_sub_with_text(recording_node, "url", video["youtube"])
        else:
            self._add_sub_with_text(recording_node, "optout", "true")

    def run(self):
        root = self.make_root()
        for day in self.schedule:
            room_node = self.add_day(root, day["index"], day["start"], day["end"])

            for venue in day["rooms"]:
                venue_node = self.add_room(room_node, venue["name"])

                for event in venue["talks"]:
                    self.add_event(venue_node, event)

        return etree.tostring(root)
