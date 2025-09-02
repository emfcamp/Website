import enum
from datetime import datetime
from typing import TYPE_CHECKING

import pytz
from pendulum import interval
from sqlalchemy import ForeignKey, func, select, text
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from main import db

from .. import BaseModel

if TYPE_CHECKING:
    from ..cfp import Proposal
    from ..user import User
    from .role import Role
    from .venue import VolunteerVenue

event_tz = pytz.timezone("Europe/London")


class ShiftEntryState(enum.StrEnum):
    SIGNED_UP = "signed_up"
    ARRIVED = "arrived"
    ABANDONED = "abandoned"
    COMPLETED = "completed"
    NO_SHOW = "no_show"


# state: [allowed next state, ] pairs
SHIFT_ENTRY_STATES: dict[ShiftEntryState, list[ShiftEntryState]] = {
    ShiftEntryState.SIGNED_UP: [
        ShiftEntryState.ARRIVED,
        ShiftEntryState.COMPLETED,
        ShiftEntryState.ABANDONED,
        ShiftEntryState.NO_SHOW,
    ],
    ShiftEntryState.ARRIVED: [
        ShiftEntryState.COMPLETED,
        ShiftEntryState.ABANDONED,
        ShiftEntryState.SIGNED_UP,
    ],
    ShiftEntryState.ABANDONED: [ShiftEntryState.ARRIVED],
    ShiftEntryState.COMPLETED: [ShiftEntryState.ARRIVED],
    ShiftEntryState.NO_SHOW: [ShiftEntryState.ARRIVED],
}


class ShiftEntryStateException(ValueError):
    """Raised when a shift entry is moved to an invalid state."""


class ShiftEntry(BaseModel):
    __tablename__ = "volunteer_shift_entry"
    __versioned__: dict = {}

    shift_id: Mapped[int] = mapped_column(ForeignKey("volunteer_shift.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    state: Mapped[ShiftEntryState] = mapped_column(default=ShiftEntryState.SIGNED_UP)

    user: Mapped["User"] = relationship(back_populates="shift_entries")
    shift: Mapped["Shift"] = relationship(back_populates="entries")

    def set_state(self, state: str | ShiftEntryState):
        if isinstance(state, str):
            try:
                state = ShiftEntryState(state)
            except ValueError as e:
                raise ShiftEntryStateException(f'"{state}" is not a valid state') from e

        if state not in self.valid_states():
            raise ShiftEntryStateException(f'"{self.state}->{state}" is not a valid transition')

        self.state = state

    def valid_states(self) -> list[ShiftEntryState]:
        return SHIFT_ENTRY_STATES[self.state]


class Shift(BaseModel):
    __tablename__ = "volunteer_shift"
    __versioned__: dict = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("volunteer_role.id"))
    venue_id: Mapped[int] = mapped_column(ForeignKey("volunteer_venue.id"))
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposal.id"))
    # TODO: should start and end be not nullable?
    start: Mapped[datetime | None] = mapped_column()
    end: Mapped[datetime | None] = mapped_column()
    min_needed: Mapped[int] = mapped_column(default=0)
    max_needed: Mapped[int] = mapped_column(default=0)

    role: Mapped["Role"] = relationship(back_populates="shifts")
    venue: Mapped["VolunteerVenue"] = relationship(back_populates="shifts")
    proposal: Mapped["Proposal"] = relationship(back_populates="shifts")
    entries: Mapped[list[ShiftEntry]] = relationship(back_populates="shift")

    current_count = column_property(
        select(func.count(ShiftEntry.shift_id))
        .where(ShiftEntry.shift_id == id)
        .correlate_except(ShiftEntry)  # type: ignore[arg-type]
        .scalar_subquery()  # type: ignore[attr-defined]
    )

    duration = column_property(end - start)

    volunteers = association_proxy("entries", "user")

    @classmethod
    def get_export_data(cls):
        return {
            "public": [
                {
                    "role": s.role.name,
                    "venue": s.venue.name,
                    "start": s.start,
                    "end": s.end,
                    "min_needed": s.min_needed,
                    "max_needed": s.max_needed,
                    "signed_up": s.current_count,
                    "entry_states": db.session.execute(
                        select(
                            [
                                ShiftEntry.state,
                                func.count(ShiftEntry.user_id),
                            ]
                        )
                        .group_by(ShiftEntry.state)
                        .where(ShiftEntry.shift_id == s.id)
                    ).all(),
                }
                for s in cls.get_all()
            ],
            "tables": ["volunteer_venue", "volunteer_shift", "volunteer_shift_entry"],
        }

    def is_clash(self, other):
        """
        If the venues and roles match then the shifts can overlap
        """

        if self.venue == other.venue and self.role == other.role:
            return False
        return other.start <= self.start <= other.end or self.start <= other.start <= self.end

    def __repr__(self):
        return f"<Shift {self.role.name}/{self.venue.name}@{self.start}>"

    def duration_in_minutes(self):
        return (self.start - self.end).total_seconds() // 60

    def to_localtime_dict(self):
        start = event_tz.localize(self.start)
        end = event_tz.localize(self.end)
        return {
            "id": self.id,
            "role_id": self.role_id,
            "venue_id": self.venue_id,
            "proposal_id": self.proposal_id,
            "start": start.strftime("%Y-%m-%dT%H:%M:00"),
            "start_time": start.strftime("%H:%M"),
            "end": end.strftime("%Y-%m-%dT%H:%M:00"),
            "end_time": end.strftime("%H:%M"),
            "min_needed": self.min_needed,
            "max_needed": self.max_needed,
            "role": self.role.to_dict(),
            "venue": self.venue.to_dict(),
            "current_count": self.current_count,
        }

    @classmethod
    def get_all(cls):
        return cls.query.order_by(Shift.start, Shift.venue_id).all()

    @classmethod
    def get_all_for_day(cls, day: str):
        """
        Return all shifts for the requested day.
        """
        return (
            cls.query.where(text("lower(to_char(start, 'Dy'))=:day").bindparams(day=day.lower()))
            .order_by(Shift.start, Shift.venue_id)
            .all()
        )

    @classmethod
    def generate_for(cls, role, venue, first, final, min, max, base_duration=120, changeover=15):
        """
        Will generate shifts between start and end times. The last shift will
        end at end.
        changeover is the changeover time in minutes.
        This will mean that during changeover there will be two shifts created.
        """

        def start(t):
            return t.subtract(minutes=changeover)

        def end(t):
            return t.add(minutes=base_duration)

        final_start = final.subtract(minutes=base_duration)

        initial_start_times = list(
            interval(first.naive(), final_start.naive()).range("minutes", base_duration)
        )

        return [
            Shift(
                role=role,
                venue=venue,
                min_needed=min,
                max_needed=max,
                start=start(t),
                end=end(t),
            )
            for t in initial_start_times
        ]


"""
class TrainingSession(Shift):
    pass
"""
