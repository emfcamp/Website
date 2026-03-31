import pendulum
import pytest

from models.volunteer import Role, Shift, VolunteerVenue


@pytest.fixture()
def role(db):
    "Yield a test volunteer role."
    name = "Test volunteer role"
    role = Role.get_by_name(name)
    if not role:
        role = Role(name=name)
        db.session.add(role)
        db.session.commit()
    yield role


@pytest.fixture()
def vol_venue(db):
    "Yield a test volunteer venue"
    name = "Test volunteer venue"
    venue = VolunteerVenue.get_by_name(name)
    if not venue:
        venue = VolunteerVenue(name=name)
        db.session.add(venue)
        db.session.commit()
    yield venue


def test_start_end(role, vol_venue):
    tz = pendulum.timezone("Europe/London")
    start = pendulum.parse("2026-07-16 09:00", tz=tz)
    end = pendulum.parse("2026-07-16 13:00", tz=tz)
    shifts = Shift.generate_for(role, vol_venue, start, end, 1, 1)
    shifts.sort(key=lambda x: x.start)
    shifts_start = pendulum.instance(shifts[0].start).set(tz=tz)
    shifts_end = pendulum.instance(shifts[-1].end).set(tz=tz)
    assert shifts_start == start.subtract(minutes=15)

    assert shifts_end == end


def test_start_end_not_multiple(role, vol_venue):
    # This one fails as period to generate shifts for is not a multiple of shift length
    # so generation leaves an unfilled gap at the end
    tz = pendulum.timezone("Europe/London")
    start = pendulum.parse("2026-07-16 09:00", tz=tz)
    end = pendulum.parse("2026-07-16 14:00", tz=tz)
    shifts = Shift.generate_for(role, vol_venue, start, end, 1, 1)
    shifts.sort(key=lambda x: x.start)
    shifts_start = pendulum.instance(shifts[0].start).set(tz=tz)
    shifts_end = pendulum.instance(shifts[-1].end).set(tz=tz)
    assert shifts_start == start.subtract(minutes=15)
    assert shifts_end == end
