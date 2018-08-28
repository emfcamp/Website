# coding=utf-8
import pytz

from pendulum import period
from sqlalchemy import select, func
from sqlalchemy.orm import validates
from sqlalchemy.ext.associationproxy import association_proxy

from main import db

event_tz = pytz.timezone('Europe/London')


class ShiftEntry(db.Model):
    __tablename__ = 'volunteer_shift_entry'
    __versioned__ = {}

    shift_id = db.Column(db.Integer, db.ForeignKey('volunteer_shift.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    checked_in = db.Column(db.Boolean, nullable=False, default=False)
    missing_others = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship('User', backref='shift_entries')
    shift = db.relationship('Shift', backref='entries')


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

    current_count = db.column_property(
        select([func.count(ShiftEntry.shift_id)]).
        where(ShiftEntry.shift_id == id)
    )

    volunteers = association_proxy('entries', 'user')

    @validates('start', 'end')
    def validate_shift_times(self, key, datetime):
        assert (datetime.minute % 15 == 0), '%s datetimes must be quarter-hour aligned' % key
        return datetime

    def is_clash(self, other):
        """
        If the venues and roles match then the shifts can overlap
        """
        return not (self.venue == other.venue and self.role == other.role) \
               or other.start <= self.start <= other.end or \
                  other.start <= self.end <= other.end

    def __repr__(self):
        return '<Shift {0}/{1}@{2}>'.format(self.role.name, self.venue.name, self.start)

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
            "start": start.strftime('%Y-%m-%dT%H:%M:00'),
            "start_time": start.strftime("%H:%M"),
            "end": end.strftime('%Y-%m-%dT%H:%M:00'),
            "end_time": end.strftime("%H:%M"),
            "min_needed": self.min_needed,
            "max_needed": self.max_needed,
            "role": self.role.to_dict(),
            "venue": self.venue.to_dict(),
            "current_count": self.current_count
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

"""
class TrainingSession(Shift):
    pass
"""

