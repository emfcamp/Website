"""
Occurrence – an instance of a ScheduleItem happening at a specific time in a
Venue (we provide for, but don’t currently actively support, multiple
Occurrences of a single ScheduleItem)
"""

from datetime import datetime

from main import db
from .. import BaseModel


class Occurrence(BaseModel):
    __versioned__ = {}
    __tablename__ = "occurrence"

    id = db.Column(db.Integer, primary_key=True)
    schedule_item_id = db.Column(
        db.Integer, db.ForeignKey("schedule_item.id", nullable=False)
    )

    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow
    )

    potential_start_time = db.Column(db.String)
    potential_time_block_id = db.Column(db.String)
    scheduled_start_time = db.Column(db.String)
    scheduled_time_block_id = db.Column(db.String)

    index = db.Column(db.Integer)

    c3voc_url = db.Column(db.String)
    youtube_url = db.Column(db.String)
    thumbnail_url = db.Column(db.String)
    video_recording_lost = db.Column(db.Boolean, nullable=False, default=False)
