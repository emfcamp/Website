from typing import Literal, TypeAlias, Union
import pytz

from pendulum import period
from sqlalchemy import select, func, text
from sqlalchemy.ext.associationproxy import association_proxy

from main import db
from .. import BaseModel

event_tz = pytz.timezone("Europe/London")


# state: [allowed next state, ] pairs
ShiftEntryState: TypeAlias = Union[
    Literal["signed_up"], Literal["arrived"], Literal["abandoned"], Literal["completed"], Literal["no_show"]
]

SHIFT_ENTRY_STATES: dict[ShiftEntryState, list[ShiftEntryState]] = {
    "signed_up": ["arrived", "completed", "abandoned", "no_show"],
    "arrived": ["completed", "abandoned", "signed_up"],
    "abandoned": ["arrived"],
    "completed": ["arrived"],
    "no_show": ["arrived"],
}


class ShiftEntryStateException(ValueError):
    """Raised when a shift entry is moved to an invalid state."""


class ShiftEntry(BaseModel):
    __tablename__ = "volunteer_shift_entry"
    __versioned__: dict = {}

    shift_id = db.Column(db.Integer, db.ForeignKey("volunteer_shift.id"), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)
    state: ShiftEntryState = db.Column(db.String, default="signed_up")

    user = db.relationship("User", backref="shift_entries")
    shift = db.relationship("Shift", backref="entries")

    def set_state(self, state: ShiftEntryState):
        if state not in SHIFT_ENTRY_STATES:
            raise ShiftEntryStateException('"%s" is not a valid state' % state)

        if state not in SHIFT_ENTRY_STATES[self.state]:
            raise ShiftEntryStateException('"%s->%s" is not a valid transition' % (self.state, state))

        self.state = state

    def valid_states(self) -> list[ShiftEntryState]:
        return SHIFT_ENTRY_STATES[self.state]


class Shift(BaseModel):
    __tablename__ = "volunteer_shift"
    __versioned__: dict = {}

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("volunteer_role.id"), nullable=False)
    venue_id = db.Column(db.Integer, db.ForeignKey("volunteer_venue.id"), nullable=False)
    proposal_id = db.Column(db.Integer, db.ForeignKey("proposal.id"), nullable=True)
    start = db.Column(db.DateTime)
    end = db.Column(db.DateTime)
    min_needed = db.Column(db.Integer, nullable=False, default=0)
    max_needed = db.Column(db.Integer, nullable=False, default=0)

    role = db.relationship("Role", backref="shifts")
    venue = db.relationship("VolunteerVenue", backref="shifts")
    proposal = db.relationship("Proposal", backref="shift")

    current_count = db.column_property(
        select([func.count(ShiftEntry.shift_id)]).where(ShiftEntry.shift_id == id).scalar_subquery()  # type: ignore[attr-defined]
    )

    duration = db.column_property(end - start)

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
                }
                for s in cls.get_all()
            ]
        }

    def is_clash(self, other):
        """
        If the venues and roles match then the shifts can overlap
        """

        if self.venue == other.venue and self.role == other.role:
            return False
        return other.start <= self.start <= other.end or self.start <= other.start <= self.end

    def __repr__(self):
        return "<Shift {0}/{1}@{2}>".format(self.role.name, self.venue.name, self.start)

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

        initial_start_times = list(period(first.naive(), final_start.naive()).range("minutes", base_duration))

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
