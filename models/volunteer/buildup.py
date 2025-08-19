from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from main import db

from .. import BaseModel, event_end, event_start

if TYPE_CHECKING:
    from .. import User

__all__ = [
    "BuildupSignupKey",
    "BuildupVolunteer",
    "buildup_end",
    "buildup_start",
    "teardown_end",
    "teardown_start",
]


class BuildupSignupKey(BaseModel):
    __table_name__ = "buildup_signup_key"
    __versioned__: dict[str, str] = {}

    token: Mapped[str] = mapped_column(primary_key=True)
    team_name: Mapped[str]


class BuildupVolunteer(BaseModel):
    __table_name__ = "buildup_volunteer"
    __versioned__: dict[str, str] = {}

    id: Mapped[int] = mapped_column(primary_key=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    user: Mapped[User] = relationship(back_populates="buildup_volunteer", foreign_keys=[user_id])

    team_name: Mapped[str] = mapped_column(default="")

    arrival_date: Mapped[datetime]
    departure_date: Mapped[datetime]

    emergency_contact: Mapped[str] = mapped_column(default="")

    acked_health_and_safety_briefing_at: Mapped[datetime | None]
    recorded_on_site: Mapped[datetime | None]

    @classmethod
    def get_for_user(cls, user: User) -> BuildupVolunteer | None:
        return db.session.scalars(select(cls).where(BuildupVolunteer.user_id == user.id)).first()


def buildup_start() -> datetime:
    # Beginning of day -7
    return datetime.combine(event_start().date() - timedelta(days=8), time(hour=0))


def buildup_end() -> date:
    # End of day 0
    return datetime.combine(event_start().date() - timedelta(days=1), time(hour=22))


def teardown_start() -> date:
    # We start considering teardown from "midday" on day 5
    return datetime.combine(event_end().date() + timedelta(days=1), time(hour=12))


def teardown_end() -> date:
    # After PM on day 8
    return datetime.combine(event_end().date() + timedelta(days=4), time(hour=22))
