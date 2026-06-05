from datetime import datetime, timedelta

import pytest
from flask_sqlalchemy import SQLAlchemy

from apps.users.calendar import (
    FavouritedScheduleItemCalendarEntry,
    OwnedScheduleItemCalendarEntry,
    VolunteerShiftCalendarEntry,
    fetch_events,
)
from models.content.schedule import Occurrence, ScheduleItem
from models.content.venue import Venue
from models.user import User
from models.volunteer.role import Role, Team
from models.volunteer.shift import Shift, ShiftEntry
from models.volunteer.venue import VolunteerVenue

# These are just arbitrary dates.
START_DATE = datetime(2026, 7, 16)
END_DATE = datetime(2026, 7, 19)

SHIFT_START_TIME = datetime(2026, 7, 17, 14, 30)
SHIFT_END_TIME = datetime(2026, 7, 17, 16, 30)


@pytest.fixture(autouse=True, scope="module")
def shift_entry(db: SQLAlchemy, user: User) -> ShiftEntry:
    team = Team(slug="test-team", name="Testers")
    role = Role(slug="test-role", name="Test Role", team=team)
    venue = VolunteerVenue(slug="stage-a", name="Stage A")
    shift = Shift(
        role=role,
        venue=venue,
        start=datetime(2026, 7, 17, 14, 30),
        end=datetime(2026, 7, 17, 16, 30),
    )
    shift_entry = ShiftEntry(user=user, shift=shift)
    db.session.add(shift_entry)
    return shift_entry


@pytest.fixture(scope="module")
def content_venue(db: SQLAlchemy) -> Venue:
    venue = Venue(name="Stage A")
    db.session.add(venue)
    return venue


@pytest.fixture(autouse=True, scope="module")
def owned_occurrence(db: SQLAlchemy, user: User, content_venue: Venue) -> Occurrence:
    schedule_item = ScheduleItem(type="talk", user=user, title="A talk")
    occurence = Occurrence(
        schedule_item=schedule_item,
        scheduled_venue=content_venue,
        occurrence_num=1,
        scheduled_duration=90,
        scheduled_time=SHIFT_START_TIME + timedelta(minutes=20),
    )

    db.session.add(occurence)
    return occurence


@pytest.fixture(autouse=True, scope="module")
def favourited_occurrence(db: SQLAlchemy, user: User, content_venue: Venue) -> Occurrence:
    speaker = User("speaker@example.org", "A Speaker")
    schedule_item = ScheduleItem(type="talk", user=speaker, title="A talk")
    schedule_item.favourited_by = [user]
    occurence = Occurrence(
        schedule_item=schedule_item,
        scheduled_venue=content_venue,
        occurrence_num=1,
        scheduled_duration=90,
        scheduled_time=SHIFT_START_TIME + timedelta(minutes=10),
    )

    db.session.add(occurence)
    return occurence


def test_fetch_events_with_volunteer_shifts(user: User, shift_entry: ShiftEntry) -> None:
    """When the user has volunteer shifts those are returned."""
    assert VolunteerShiftCalendarEntry(shift_entry) in fetch_events(user, START_DATE, END_DATE)


def test_fetch_events_with_favourited_content(user: User, favourited_occurrence: Occurrence) -> None:
    """When the user has favourited some content."""
    assert FavouritedScheduleItemCalendarEntry(favourited_occurrence) in fetch_events(
        user, START_DATE, END_DATE
    )


def test_fetch_events_with_owned_content(user: User, owned_occurrence: Occurrence) -> None:
    """When the user has some content they're running in the schedule."""
    assert OwnedScheduleItemCalendarEntry(owned_occurrence) in fetch_events(user, START_DATE, END_DATE)


def test_events_are_sorted_by_start_time(user: User) -> None:
    assert [entry.type for entry in fetch_events(user, START_DATE, END_DATE)] == [
        "volunteer_shift",
        "favourited_content",
        "owned_content",
    ]
