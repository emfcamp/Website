from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select

from main import db
from models.user import User
from models.volunteer.shift import Shift, ShiftEntry


@dataclass
class CalendarEntry:
    start_time: datetime
    end_time: datetime


class VolunteerShiftCalendarEntry(CalendarEntry):
    shift: Shift
    shift_entry: ShiftEntry

    def __init__(self, shift_entry: ShiftEntry):
        self.type = "volunteer_shift"
        self.shit_entry = shift_entry
        self.shift = shift_entry.shift
        self.start_time = self.shift.start
        self.end_time = self.shift.end


def fetch_events(user: User, start: datetime, end: datetime) -> list[CalendarEntry]:
    """Return a list of calendar entries for a user."""
    events = [
        VolunteerShiftCalendarEntry(shift)
        for shift in db.session.scalars(
            select(ShiftEntry)
            .where(ShiftEntry.user_id == user.id)
            .where(Shift.start >= start)
            .where(Shift.end <= end)
            .order_by(Shift.start)
        )
    ]

    return events
