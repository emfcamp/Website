# coding=utf-8
from sqlalchemy.orm import validates
from pendulum import period

from main import db

class Shift(db.Model):
    __tablename__ = 'volunteer_shift'
    __versioned__ = {}

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('volunteer_role.id'), nullable=False)
    venue_id = db.Column(db.Integer, db.ForeignKey('volunteer_venue.id'), nullable=False)
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposal.id'), nullable=True)
    start = db.Column(db.DateTime)
    end = db.Column(db.DateTime)
    min_needed = db.Column(db.Integer, nullable=False, default=0)
    max_needed = db.Column(db.Integer, nullable=False, default=0)

    role = db.relationship('Role', backref='shifts')
    venue = db.relationship('VolunteerVenue', backref='shifts')

    @validates('start', 'end')
    def validate_shift_times(self, key, datetime):
        assert (datetime.minute % 15 == 0), '%s datetimes must be quarter-hour aligned' % key
        return datetime

    def __repr__(self):
        return '<Shift {0}/{1}@{2}>'.format(self.role.name, self.venue.name, self.start)

    def duration_in_minutes(self):
        return (self.start - self.end).total_seconds() // 60

    def to_dict(self):
        return {
            "id": self.id,
            "role_id": self.role_id,
            "venue_id": self.venue_id,
            "proposal_id": self.proposal_id,
            "start": self.start,
            "start_time": self.start.strftime("%H:%M"),
            "end": self.end,
            "end_time": self.end.strftime("%H:%M"),
            "min_needed": self.min_needed,
            "max_needed": self.max_needed,
            "role": self.role.to_dict(),
            "venue": self.venue.to_dict(),
            "current_count": len(self.entries)
        }

    @classmethod
    def get_all(cls):
        return cls.query.order_by(Shift.start, Shift.venue_id).all()

    @classmethod
    def generate_for(cls, role, venue, first, final, min, max, base_duration=180, changeover=15):
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

        initial_start_times = list(period(first.naive(), final_start.naive()).range('minutes', base_duration))

        return [Shift(role=role, venue=venue, min_needed=min, max_needed=max,
                      start=start(t), end=end(t))
                for t in initial_start_times]


class ShiftEntry(db.Model):
    __tablename__ = 'volunteer_shift_entry'
    __versioned__ = {}

    shift_id = db.Column(db.Integer, db.ForeignKey('volunteer_shift.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    checked_in = db.Column(db.Boolean, nullable=False, default=False)
    missing_others = db.Column(db.Boolean, nullable=False, default=False)

    shift_details = db.relationship('Shift', backref='entries')
    user_details = db.relationship('Shift', backref='shift_entries')

"""
class TrainingSession(Shift):
    pass
"""

