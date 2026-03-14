from datetime import datetime, time, timedelta
from functools import cache
from uuid import NAMESPACE_URL, uuid5

from lxml import etree

from main import external_url
from models import event_end, event_start, event_year

from . import event_tz


class FrabExporter:
    def __init__(self, schedule):
        self.schedule = schedule

    @cache
    def format_duration(self, start_time: datetime, end_time: datetime) -> timedelta:
        # str(timedelta) creates e.g. hrs:min:sec...
        duration = (end_time - start_time).total_seconds() / 60
        hours = int(duration // 60)
        minutes = int(duration % 60)
        if hours < 24:
            return f"{hours:d}:{minutes:02d}"
        days = int(hours // 24)
        hours = int(hours % 24)
        return f"{days:d}:{hours:02d}:{minutes:02d}"

    @cache
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


class FrabJsonExporter(FrabExporter):
    def run(self):
        raise NotImplementedError


class FrabXmlExporter(FrabExporter):
    def _add_sub_with_text(self, parent, element, text, **extra):
        node = etree.SubElement(parent, element, **extra)
        node.text = text
        return node

    def make_root(self):
        root = etree.Element("schedule")

        self._add_sub_with_text(root, "version", "1.0-public")

        conference = etree.SubElement(root, "conference")

        self._add_sub_with_text(conference, "title", f"Electromagnetic Field {event_year()}")
        self._add_sub_with_text(conference, "acronym", f"emf{event_year()}")
        self._add_sub_with_text(conference, "start", event_start().strftime("%Y-%m-%d"))
        self._add_sub_with_text(conference, "end", event_end().strftime("%Y-%m-%d"))
        self._add_sub_with_text(conference, "days", "3")
        self._add_sub_with_text(conference, "timeslot_duration", "00:10")

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
        url = external_url("schedule.item", year=event_year(), proposal_id=event["id"], slug=event["slug"])

        event_node = etree.SubElement(room, "event", id=str(event["id"]), guid=str(uuid5(NAMESPACE_URL, url)))

        self._add_sub_with_text(event_node, "room", room.attrib["name"])
        self._add_sub_with_text(event_node, "title", event["title"])

        event_type = event.get("type", "talk")
        self._add_sub_with_text(event_node, "type", event_type)
        # infobeamer frab scheduler can color by "track"
        self._add_sub_with_text(event_node, "track", event_type)

        self._add_sub_with_text(event_node, "date", event["start_date"].isoformat())
        self._add_sub_with_text(event_node, "url", url)

        # Start time
        self._add_sub_with_text(event_node, "start", event["start_date"].strftime("%H:%M"))

        duration = self.get_duration(event["start_date"], event["end_date"])
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
        video = event.get("video", {})

        recording_node = etree.SubElement(event_node, "recording")

        self._add_sub_with_text(recording_node, "license", "CC BY-SA 4.0")
        self._add_sub_with_text(
            recording_node, "optout", "false" if event.get("video_privacy") == "public" else "true"
        )
        if "ccc" in video:
            self._add_sub_with_text(recording_node, "url", video["ccc"])
        elif "youtube" in video:
            self._add_sub_with_text(recording_node, "url", video["youtube"])

    def run(self):
        root = self.make_root()
        days_dict = {}
        index = 0

        for event in self.schedule:
            day_start, day_end = self.get_day_start_end(event["start_date"])
            day_key = day_start.strftime("%Y-%m-%d")
            venue_key = event["venue"]

            if day_key not in days_dict:
                index += 1
                node = self.add_day(root, index, day_start, day_end)
                days_dict[day_key] = {"node": node, "rooms": {}}

            day = days_dict[day_key]

            if venue_key not in day["rooms"]:
                day["rooms"][venue_key] = self.add_room(day["node"], venue_key)

            self.add_event(day["rooms"][venue_key], event)

        return etree.tostring(root)
