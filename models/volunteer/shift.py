import enum
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from math import ceil, floor
from typing import TYPE_CHECKING, Self, TypedDict

import pytz
from sqlalchemy import ForeignKey, delete, desc, func, select
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from apps.config import config
from main import db
from models.volunteer.venue import VolunteerVenue

from .. import BaseModel

if TYPE_CHECKING:
    from ..content.schedule import Occurrence
    from ..user import User
    from .role import Role

__all__ = [
    "Shift",
    "ShiftEntry",
    "ShiftEntryState",
    "ShiftEntryStateException",
    "ShiftTemplate",
]

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
    """Join table used to indicate a volunteer has signed up for a given shift."""

    __tablename__ = "volunteer_shift_entry"
    __versioned__: dict[str, str] = {}

    shift_id: Mapped[int] = mapped_column(ForeignKey("volunteer_shift.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)

    #: Indicates whether a volunteer has arrived for/completed a shift.
    state: Mapped[ShiftEntryState] = mapped_column(default=ShiftEntryState.SIGNED_UP)

    user: Mapped[User] = relationship(back_populates="shift_entries")
    shift: Mapped[Shift] = relationship(back_populates="entries")

    def set_state(self, state: str | ShiftEntryState) -> None:
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

    def eligible_for_checkin_at(self, now: datetime) -> bool:
        """Checks if we can transition to ARRIVED and the shift starts in 15 minutes or less from now."""
        return ShiftEntryState.ARRIVED in self.valid_states() and self.shift.start >= now - timedelta(
            minutes=15
        )

    def eligible_for_checkout_at(self, now: datetime) -> bool:
        """Checks if we can transition to a checked out state."""
        return (
            ShiftEntryState.ABANDONED in self.valid_states()
            or ShiftEntryState.COMPLETED in self.valid_states()
        )

    def eligible_for_completion_at(self, now: datetime) -> bool:
        """Checks if we can transition to COMPLETED and a sufficient portion of the shift has passed."""
        return ShiftEntryState.COMPLETED in self.valid_states() and self.shift.end <= now + timedelta(
            minutes=15
        )


class ShiftTemplateExport(TypedDict):
    role_slug: str
    venue_slug: str
    event_day: int
    start_time: str
    end_time: str
    duration: int
    changeover_time: int
    min_needed: int
    max_needed: int
    notes: str


class ShiftTemplate(BaseModel):
    """Configuration for creating a block of Shift instances.

    When setting up the volunteer system for a new event we start with a collecion
    of ShiftTemplates for each role and venue. These are then used to generate
    a number of concrete Shift instances of the correct duration to fill the specified
    period for the template.

    A given role/venue combination may make use of multiple ShiftTemplate instances
    to cover the various staffing levels and periods required.

    Warning: ShiftTemplates will destroy all resulting Shift instances when deleted
    or when shifts are regenerated. This is not a safe operation to perform once
    volunteers have started signing up for shifts. When working via the web interface
    doing so will be prevented but if you're on a console you should be aware of this.
    """

    __tablename__ = "volunteer_shift_template"
    __versioned__: dict[str, str] = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("volunteer_role.id", ondelete="CASCADE"))
    venue_id: Mapped[int] = mapped_column(ForeignKey("volunteer_venue.id", ondelete="CASCADE"))
    event_day: Mapped[int] = mapped_column()
    start_time: Mapped[time] = mapped_column()
    end_time: Mapped[time] = mapped_column()
    duration: Mapped[int] = mapped_column(default=120)
    changeover_time: Mapped[int] = mapped_column(default=15)
    min_needed: Mapped[int] = mapped_column(default=0)
    max_needed: Mapped[int] = mapped_column(default=0)
    notes: Mapped[str] = mapped_column(default="")

    role: Mapped[Role] = relationship("Role", back_populates="shift_templates")
    venue: Mapped[VolunteerVenue] = relationship("VolunteerVenue")
    shifts: Mapped[list[Shift]] = relationship(
        "Shift", back_populates="generated_from", cascade="all, delete-orphan"
    )

    @classmethod
    def get_export_data(cls) -> dict[str, list[ShiftTemplateExport | str]]:
        return {
            "public": [
                {
                    "role_slug": template.role.slug,
                    "venue_slug": template.venue.slug,
                    "event_day": template.event_day,
                    "start_time": template.start_time.toisoformat(),
                    "end_time": template.finish_time.toisoformat(),
                    "duration": template.duration,
                    "changeover_time": template.changeover_time,
                    "min_needed": template.min_needed,
                    "max_needed": template.max_needed,
                    "notes": template.notes,
                }
                for template in cls.query.all()  # type: ignore
            ],
            "tables": ["volunteer_shift_template"],
        }

    @property
    def start_date(self) -> date:
        return config.event_start.date() + timedelta(days=self.event_day - 1)

    @property
    def start_datetime(self) -> datetime:
        return event_tz.localize(datetime.combine(self.start_date, self.start_time))

    @property
    def end_date(self) -> date:
        return self.start_date if self.start_time < self.end_time else self.start_date + timedelta(days=1)

    @property
    def end_datetime(self) -> datetime:
        return event_tz.localize(datetime.combine(self.end_date, self.end_time))

    @property
    def shift_timings(self) -> list[tuple[datetime, int]]:
        """Return a list of (start_time, duration) tuples to be turned into shifts."""
        period = (self.end_datetime - self.start_datetime).seconds // 60

        num_shifts = round(period / self.duration)
        if num_shifts == 0:
            num_shifts = 1

        # Sometimes we can't fit an exact multiple of duration into the
        # time period covered by a template. `slop` is the number of minutes
        # we're out by, which can be positive or negative.
        slop = period - num_shifts * self.duration

        # `adj` is used to try and keep shift duration adjustments to multiples
        # of 15 minutes.
        if slop >= 0:
            adj = 15 * ceil(slop / num_shifts / 15)
        else:
            adj = 15 * floor(slop / num_shifts / 15)

        # Calculate start times
        shift_starts = []
        time = self.start_datetime
        while time < self.end_datetime:
            if slop != 0:
                # If there's only a little bit of slop left apply it in its entirety
                # to this shift.
                if abs(slop) < abs(adj):
                    this_duration = self.duration + slop
                    slop = 0

                # Otherwise apply a bigger chunk of adjustment and leave some
                # slop for the next shift.
                else:
                    this_duration = self.duration + adj
                    slop -= adj
            else:
                this_duration = self.duration

            shift_starts.append((time, this_duration))
            time = time + timedelta(minutes=this_duration)

        return shift_starts

    def build_shifts(self) -> list[Shift]:
        return [
            Shift(
                generated_from=self,
                role=self.role,
                venue=self.venue,
                min_needed=self.min_needed,
                max_needed=self.max_needed,
                start=(shift_start - timedelta(minutes=self.changeover_time))
                .astimezone(pytz.utc)
                .replace(tzinfo=None),
                end=(shift_start + timedelta(minutes=duration)).astimezone(pytz.utc).replace(tzinfo=None),
            )
            for shift_start, duration in self.shift_timings
        ]

    def regenerate_shifts(self) -> None:
        db.session.execute(delete(Shift).where(Shift.shift_template_id == self.id))
        db.session.add_all(self.build_shifts())

    def __repr__(self) -> str:
        return f"<ShiftTemplate(id={self.id})>"


class Shift(BaseModel):
    """An available shift for one or more volunteers to perform."""

    __tablename__ = "volunteer_shift"
    __versioned__: dict[str, str] = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("volunteer_role.id", ondelete="CASCADE"))
    venue_id: Mapped[int] = mapped_column(ForeignKey("volunteer_venue.id", ondelete="CASCADE"))
    shift_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("volunteer_shift_template.id", ondelete="CASCADE")
    )

    occurrence_id: Mapped[int | None] = mapped_column(ForeignKey("occurrence.id"))
    start: Mapped[datetime] = mapped_column()
    end: Mapped[datetime] = mapped_column()

    #: Minimum number of volunteers required for the shift
    min_needed: Mapped[int] = mapped_column(default=0)
    #: Maximum number of volunteers required for the shift
    max_needed: Mapped[int] = mapped_column(default=0)

    #: Role that this shift is filling
    role: Mapped[Role] = relationship(back_populates="shifts")
    #: Venue where the shift occurs
    venue: Mapped[VolunteerVenue] = relationship(back_populates="shifts")
    #: Optional Occurrence (talk/workshop) related to this shift
    occurrence: Mapped[Occurrence] = relationship(back_populates="shifts")
    #: Entries (volunteers) for this shift
    entries: Mapped[list[ShiftEntry]] = relationship(back_populates="shift")
    #: The ShiftTemplate that resulted in this shift
    generated_from: Mapped[ShiftTemplate | None] = relationship(back_populates="shifts")

    #: Additional notes for this shift, primarily used for workshop helpers where every
    #: shift has slightly different requirements.
    notes: Mapped[str | None] = mapped_column(default=None)

    current_count = column_property(
        select(func.count(ShiftEntry.shift_id))
        .where(ShiftEntry.shift_id == id)
        .correlate_except(ShiftEntry)
        .scalar_subquery()
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
        """Calculate whether this shift clashes with another.

        We use this to determine if we should allow a volunteer to sign up for
        both shifts, which is only permitted if the other shift is filling the
        same role in the same venue. In all other cases a volunteer can't sign
        up for two shifts at the same time.

        This is needed because contiguous shifts often have a slight overlap.
        """
        # If the venues and roles match then the shifts can overlap.
        if self.venue == other.venue and self.role == other.role:
            return False
        return other.start <= self.start <= other.end or self.start <= other.start <= self.end

    def __repr__(self):
        return f"<Shift {self.role.name}/{self.venue.name}@{self.start}>"

    def duration_in_minutes(self):
        return (self.start - self.end).total_seconds() // 60

    @property
    def local_start(self):
        """Shift start time in the event timezone."""
        return event_tz.fromutc(self.start)

    @property
    def local_end(self):
        """Shift end time in the event timezone."""
        return event_tz.fromutc(self.end)

    def to_localtime_dict(self):
        return {
            "id": self.id,
            "role_id": self.role_id,
            "venue_id": self.venue_id,
            "occurrence_id": self.occurrence_id,
            "start": self.local_start.strftime("%Y-%m-%dT%H:%M:00"),
            "start_time": self.local_start.strftime("%H:%M"),
            "end": self.local_end.strftime("%Y-%m-%dT%H:%M:00"),
            "end_time": self.local_end.strftime("%H:%M"),
            "min_needed": self.min_needed,
            "max_needed": self.max_needed,
            "role": self.role.to_dict(),
            "venue": self.venue.to_dict(),
            "notes": self.notes,
            "current_count": self.current_count,
        }

    @classmethod
    def get_all(cls):
        return cls.query.order_by(Shift.start, Shift.venue_id).all()

    @classmethod
    def get_all_for_day(cls, day: date, *, include_unfinalised: bool = False) -> Sequence[Self]:
        """Return all shifts for the requested day.

        For the purposes of shifts we consider a day to run from 04:00-03:59 so
        that late night shifts get shown in the context of the day leading up to
        them.

        If `include_unfinalised` is True than all shifts will be returned, otherwise
        only those from finalised roles will be returned.
        """
        next_day = day + timedelta(days=1)
        start = event_tz.localize(datetime.strptime(f"{day} 03:59:00", "%Y-%m-%d %H:%M:%S"))
        end = event_tz.localize(datetime.strptime(f"{next_day} 04:00:00", "%Y-%m-%d %H:%M:%S"))

        query = (
            select(cls)
            .join(Shift.venue)
            .where(Shift.start >= start)
            .where(Shift.end <= end)
            .order_by(Shift.start, Shift.end, VolunteerVenue.name)
        )

        if not include_unfinalised:
            # Unless we import only when the function is called we end up with a circular import.
            from .role import Role

            query = query.join(Shift.role).where(Role.shifts_finalised)

        return db.session.execute(query).scalars().all()

    @classmethod
    def earliest_and_latest_in_range(
        cls, start: datetime, end: datetime
    ) -> tuple[datetime | None, datetime | None]:
        """Return the earliest and latest shift available to a volunteer."""

        query = select(cls.start).where((cls.start >= start) & (cls.end <= end))
        first = db.session.execute(query.order_by(cls.start)).scalar()
        last = db.session.execute(query.order_by(desc(cls.end))).scalar()

        return (first, last)


"""
class TrainingSession(Shift):
    pass
"""
