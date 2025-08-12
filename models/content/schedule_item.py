"""
ScheduleItem – a piece of content (official or otherwise) which can be
scheduled to happen at a specific time and place. It may have multiple owners.
"""

from datetime import datetime

from main import db
from .. import BaseModel
from .. import User


UserScheduleItem = db.Table(
    "user_schedule_items",
    BaseModel.metadata,
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column(
        "schedule_item_id",
        db.Integer,
        db.ForeignKey("schedule_item.id"),
        primary_key=True,
        index=True,
    ),
)

FavouriteProposal = db.Table(
    "favourite_proposal",
    BaseModel.metadata,
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column(
        "proposal_id",
        db.Integer,
        db.ForeignKey("proposal.id"),
        primary_key=True,
        index=True,
    ),
)


class ScheduleItem(BaseModel):
    __versioned__ = {"exclude": ["favourites"]}
    __tablename__ = "schedule_item"

    id = db.Column(db.Integer, primary_key=True)
    users = db.relationship(
        User, secondary=UserScheduleItem, backref=db.backref("schedule_items")
    )
    type = db.Column(db.string, nullable=False)
    state = db.Column(db.string, nullable=False, default="new")
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow
    )

    names = db.Column(db.string)
    pronouns = db.Column(db.string)
    title = db.Column(db.string, nullable=False)
    description = db.Column(db.string, nullable=False)

    proposal_id = db.Column(db.Integer, db.ForeignKey("proposal.id"))

    duration = db.Column(db.string)
    arrival_period = db.Column(db.string)
    departure_period = db.Column(db.string)
    available_times = db.Column(db.string)

    telephone_number = db.Column(db.string)
    eventphone_number = db.Column(db.string)

    occurences = db.relationship("Occurrences", backref="schedule_item")
    favourites = db.relationship(
        User, secondary=FavouriteProposal, backref=db.backref("favourites")
    )
