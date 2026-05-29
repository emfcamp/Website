from datetime import datetime

import pytest
from flask_sqlalchemy import SQLAlchemy

from apps.users.calendar import VolunteerShiftCalendarEntry, fetch_events
from models.user import User
from models.volunteer.role import Role, Team
from models.volunteer.shift import Shift, ShiftEntry
from models.volunteer.venue import VolunteerVenue

# These are just arbitrary dates.
START_DATE = datetime(2026, 7, 16)
END_DATE = datetime(2026, 7, 19)


@pytest.fixture(scope="module")
def team(db: SQLAlchemy) -> Team:
    team = Team(slug="test-team", name="Testers")
    db.session.add(team)
    return team


@pytest.fixture(scope="module")
def role(db: SQLAlchemy, team: Team) -> Role:
    role = Role(slug="test-role", name="Test Role", team=team)
    db.session.add(role)
    return role


@pytest.fixture(scope="module")
def volunteer_venue(db: SQLAlchemy) -> VolunteerVenue:
    venue = VolunteerVenue(slug="stage-a", name="Stage A")
    db.session.add(venue)
    return venue


@pytest.fixture(scope="module")
def shift(db: SQLAlchemy, role: Role, volunteer_venue: VolunteerVenue) -> Shift:
    shift = Shift(
        role=role,
        venue=volunteer_venue,
        start=datetime(2026, 7, 17, 14, 30),
        end=datetime(2026, 7, 17, 16, 30),
    )
    db.session.add(shift)
    return shift


@pytest.fixture
def shift_entry(db: SQLAlchemy, user: User, shift: Shift) -> ShiftEntry:
    shift_entry = ShiftEntry(user=user, shift=shift)
    db.session.add(shift_entry)
    return shift_entry


def test_fetch_events_with_no_events(user: User) -> None:
    """When the user has no events the calendar is an empty list."""
    assert fetch_events(user, START_DATE, END_DATE) == []


def test_fetch_events_with_volunteer_shifts(user: User, shift_entry: ShiftEntry) -> None:
    """When the user has volunteer shifts those are returned."""
    assert fetch_events(user, START_DATE, END_DATE) == [VolunteerShiftCalendarEntry(shift_entry)]
