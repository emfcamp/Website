from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, TypedDict

from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import INTERVAL
from sqlalchemy.orm import InstrumentedAttribute, with_parent

from apps.schedule import event_tz
from main import db
from models.content.schedule import Occurrence, ScheduleItem
from models.user import User
from models.volunteer.shift import Shift, ShiftEntry


class CalendarDict(TypedDict):
    type: str
    human_type: str
    title: str
    conflict_priority: int
    start_time: str
    end_time: str
    venue_name: str | None
    venue_mapref: str | None


@dataclass
class CalendarEntry:
    type: Literal["volunteer_shift", "favourited_content", "owned_content"]
    title: str
    start_time: datetime
    end_time: datetime
    venue_name: str | None
    venue_mapref: str | None
    human_type: str = "Event"
    conflict_priority: int = 99

    def overlaps_with(self, start_time: datetime, end_time: datetime) -> bool:
        """Does any part of this calendar entry occur between start_time and end_time?"""
        return self.start_time < end_time and self.end_time > start_time

    def to_dict(self) -> CalendarDict:
        return {
            "type": self.type,
            "human_type": self.human_type,
            "title": self.title,
            "conflict_priority": self.conflict_priority,
            "start_time": self.start_time.strftime("%Y-%m-%dT%H:%M:00"),
            "end_time": self.end_time.strftime("%Y-%m-%dT%H:%M:00"),
            "venue_name": self.venue_name,
            "venue_mapref": self.venue_mapref,
        }


class VolunteerShiftCalendarEntry(CalendarEntry):
    type: Literal["volunteer_shift"] = "volunteer_shift"
    human_type = "Volunteer Shift"
    conflict_priority: int = 0
    shift: Shift
    shift_entry: ShiftEntry

    def __init__(self, shift_entry: ShiftEntry):
        self.shit_entry = shift_entry
        self.shift = shift_entry.shift
        self.title = shift_entry.shift.role.name
        self.start_time = self.shift.local_start
        self.end_time = self.shift.local_end
        self.venue_name = self.shift.venue.name
        self.venue_mapref = self.shift.venue.mapref


class OccurrenceCalendarEntry(CalendarEntry):
    occurrence: Occurrence

    def __init__(self, occurrence: Occurrence):
        # This is mostly here so that mypy knows scheduled_venue is set.
        if not occurrence.scheduled or occurrence.scheduled_venue is None:
            raise ValueError("Only scheduled content can result in calendar entries.")

        self.occurrence = occurrence
        self.title = occurrence.schedule_item.title
        self.start_time = event_tz.localize(occurrence.scheduled_time)  # type: ignore
        self.end_time = event_tz.localize(occurrence.scheduled_end_time)  # type: ignore
        self.venue_name = occurrence.scheduled_venue.name
        self.venue_mapref = occurrence.scheduled_venue.map_link


class FavouritedScheduleItemCalendarEntry(OccurrenceCalendarEntry):
    type: Literal["favourited_content"] = "favourited_content"
    human_type = "Favourite"
    conflict_priority: int = 2


class OwnedScheduleItemCalendarEntry(OccurrenceCalendarEntry):
    type: Literal["owned_content"] = "owned_content"
    human_type = "Your Content"
    conflict_priority: int = 1


def _occurrences_with_parent(
    user: User, start: datetime, end: datetime, join_via: InstrumentedAttribute[list[ScheduleItem]]
) -> Sequence[Occurrence]:
    occurrence_end = Occurrence.scheduled_time + cast("1 minute", INTERVAL) * Occurrence.scheduled_duration
    return db.session.scalars(
        select(Occurrence)
        .join(Occurrence.schedule_item)
        .where(with_parent(user, join_via))
        .where(Occurrence.scheduled_time < end)
        .where(occurrence_end > start)
    ).all()


def fetch_events(user: User, start: datetime, end: datetime) -> Sequence[CalendarEntry]:
    """Return a list of calendar entries for a user."""
    calendar: list[CalendarEntry] = []
    calendar += [
        VolunteerShiftCalendarEntry(shift)
        for shift in db.session.scalars(
            select(ShiftEntry)
            .where(with_parent(user, User.shift_entries))
            .join(ShiftEntry.shift)
            .where(Shift.start < end)
            .where(Shift.end > start)
        )
    ]

    calendar += [
        FavouritedScheduleItemCalendarEntry(occurrence)
        for occurrence in _occurrences_with_parent(user, start, end, User.favourites)
    ]

    calendar += [
        OwnedScheduleItemCalendarEntry(occurrence)
        for occurrence in _occurrences_with_parent(user, start, end, User.schedule_items)
    ]

    return sorted(calendar, key=lambda e: e.start_time)
