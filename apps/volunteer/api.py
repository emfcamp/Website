from datetime import datetime
from typing import TypedDict

from sqlalchemy import and_

from models.volunteer.shift import Shift

from . import volunteer


class ShiftResponse(TypedDict):
    id: int
    role: str
    venue: str | None
    min_needed: int
    max_needed: int
    current: int
    start: datetime | None
    end: datetime | None


def serialize_shift(shift: Shift) -> ShiftResponse:
    return {
        "id": shift.id,
        "role": shift.role.name,
        "venue": shift.venue.name,
        "min_needed": shift.min_needed,
        "max_needed": shift.max_needed,
        "current": shift.current_count,
        "start": shift.start,
        "end": shift.end,
    }


@volunteer.route("/info-beamer.json")
def volunteer_json():
    """Basic API to get volunteer needs on Info Beamer screens."""
    urgent_shifts = (
        Shift.query.filter(and_(Shift.end >= datetime.now(), Shift.current_count < Shift.min_needed))
        .order_by(Shift.start)
        .limit(10)
        .all()
    )
    non_urgent_shifts = (
        Shift.query.filter(
            and_(
                Shift.end >= datetime.now(),
                Shift.current_count < Shift.max_needed,
                Shift.current_count >= Shift.min_needed,
            )
        )
        .order_by(Shift.start)
        .limit(10)
        .all()
    )

    return {
        "urgent_shifts": [serialize_shift(shift) for shift in urgent_shifts],
        "non_urgent_shifts": [serialize_shift(shift) for shift in non_urgent_shifts],
    }
