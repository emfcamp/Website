"""
ScheduleAttribute – key/value store of additional information associated with
a Proposal or ScheduleItem (e.g. workshop capacity, equipment required)
"""

from datetime import datetime

from main import db
from .. import BaseModel


class ScheduleAttribute(BaseModel):
    __versioned__ = {}
    __tablename__ = "schedule_attribute"

    id = db.Column(db.Integer, primary_key=True)
    schedule_item_id = db.Column(
        db.Integer, db.ForeignKey("schedule_item.id", nullable=False)
    )

    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow
    )

    key = db.Column(db.string, nullable=False, index=True)
    value = db.Column(db.string)
