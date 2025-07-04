"""
TimeBlock – a block of time when occurrences of a specific content type are
allowed to be scheduled in a Venue.
"""

from datetime import datetime

from main import db
from .. import BaseModel


class TimeBlock(BaseModel):
    __versioned__ = {}
    __tablename__ = "time_block"

    id = db.Column(db.Integer, primary_key=True)
    # FIXME move venue in to models/content
    venue_id = db.Column(db.Integer, db.ForeignKey("venue.id"), nullable=False)

    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow
    )

    start_time = db.Column(db.string, nullable=False)
    duration = db.Column(db.string, nullable=False)

    allowed_types = db.Column(db.string)

    occurrences = db.relationship("Occurrence", backref="time_block")
