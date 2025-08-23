from datetime import datetime, timedelta, time, date

from sqlalchemy.orm import backref

from main import db
from .. import event_start, event_end
from .. import BaseModel


__all__ = [
    "BuildupSignupKey",
    "BuildupVolunteer",
    "buildup_start",
    "buildup_end",
    "teardown_start",
    "teardown_end",
]


class BuildupSignupKey(BaseModel):
    __table_name__ = "buildup_signup_key"
    __versioned__: dict = {}

    token = db.Column(db.String, nullable=False, primary_key=True)
    team_name = db.Column(db.String, nullable=False)


class BuildupVolunteer(BaseModel):
    __table_name__ = "buildup_volunteer"
    __versioned__: dict = {}

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref=backref("buildup_volunteer", uselist=False))

    team_name = db.Column(db.String, nullable=False, server_default="")

    arrival_date = db.Column(db.DateTime)
    departure_date = db.Column(db.DateTime)

    emergency_contact = db.Column(db.String, nullable=False, server_default="")

    acked_health_and_safety_briefing_at = db.Column(db.DateTime, nullable=True)
    recorded_on_site = db.Column(db.DateTime, nullable=True)

    @classmethod
    def get_for_user(cls, user):
        return cls.query.filter_by(user_id=user.id).first()


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
