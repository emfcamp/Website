from datetime import date, datetime, time, timedelta

import pytest
from flask_sqlalchemy import SQLAlchemy

from apps.config import config
from models.volunteer.role import Role, Team
from models.volunteer.shift import ShiftTemplate, event_tz
from models.volunteer.venue import VolunteerVenue


@pytest.fixture(scope="module")
def role(db: SQLAlchemy) -> Role:
    team = Team(name="Test Team", slug="test")
    role = Role(name="Test Role", slug="test", team=team)
    db.session.add(role)
    return role


@pytest.fixture(scope="module")
def venue(db: SQLAlchemy) -> VolunteerVenue:
    venue = VolunteerVenue(name="Test", slug="test")
    db.session.add(venue)
    return venue


@pytest.fixture
def template(role: Role, venue: VolunteerVenue) -> ShiftTemplate:
    return ShiftTemplate(
        role=role,
        venue=venue,
        event_day=1,
        start_time=time(9, 0),
        end_time=time(13, 0),
        duration=60,
        changeover_time=10,
        min_needed=1,
        max_needed=5,
    )


@pytest.fixture
def shift_date() -> date:
    # Event day 1 is the listed start date.
    return config.event_start.date()


def test_start_date(template: ShiftTemplate, shift_date: date):
    assert template.start_date == shift_date


def test_end_date_on_same_day(template: ShiftTemplate, shift_date: date):
    assert template.end_date == shift_date


def test_end_date_on_next_day(template: ShiftTemplate, shift_date: date):
    template.end_time = time(2, 0)
    assert template.end_date == shift_date + timedelta(days=1)


def test_shift_start_times(template: ShiftTemplate, shift_date: date):
    assert template.shift_start_times == [
        event_tz.localize(datetime.combine(shift_date, time(hour, 0, 0))) for hour in range(9, 13)
    ]


def test_build_shifts(template: ShiftTemplate, role: Role, venue: VolunteerVenue, shift_date: date):
    shifts = template.build_shifts()
    assert len(shifts) == 4

    shift = shifts[0]
    assert shift.start == datetime.combine(shift_date, time(7, 50, 0), None)
    assert shift.end == datetime.combine(shift_date, time(9, 0, 0), None)
    assert shift.min_needed == template.min_needed
    assert shift.max_needed == template.max_needed
    assert shift.role == role
    assert shift.venue == venue
    assert shift.generated_from == template
