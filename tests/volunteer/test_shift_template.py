from datetime import time, timedelta

import pytest
from flask_sqlalchemy import SQLAlchemy

from apps.config import config
from models.volunteer.role import Role, Team
from models.volunteer.shift import ShiftTemplate
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


def test_start_date(template: ShiftTemplate):
    assert template.start_date == config.event_start.date()


def test_end_date_on_same_day(template: ShiftTemplate):
    assert template.end_date == config.event_start.date()


def test_end_date_on_next_day(template: ShiftTemplate):
    template.end_time = time(2, 0)
    assert template.end_date == config.event_start.date() + timedelta(days=1)


def test_shift_start_times(template: ShiftTemplate):
    assert template.shift_start_times == [
        template.start_datetime,
        template.start_datetime + timedelta(minutes=60),
        template.start_datetime + timedelta(minutes=120),
        template.start_datetime + timedelta(minutes=180),
    ]


def test_build_shifts(template: ShiftTemplate, role: Role, venue: VolunteerVenue):
    shifts = template.build_shifts()
    assert len(shifts) == 4

    shift = shifts[0]
    assert shift.start == template.start_datetime - timedelta(minutes=template.changeover_time)
    assert shift.end == template.start_datetime + timedelta(minutes=template.duration)
    assert shift.min_needed == template.min_needed
    assert shift.max_needed == template.max_needed
    assert shift.role == role
    assert shift.venue == venue
    assert shift.generated_from == template
