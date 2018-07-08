# coding=utf-8
from main import db


class Shift(db.Model):
    __tablename__ = 'shift'
    __versioned__ = {}

    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=False)
    venue_id = db.Column(db.Integer, db.ForeignKey('venue.id'), nullable=False)
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposal.id'), nullable=True)
    start = db.Column(db.DateTime)
    end = db.Column(db.DateTime)
    min_needed = db.Column(db.Integer, nullable=False, default=0)
    max_needed = db.Column(db.Integer, nullable=False, default=0)

class ShiftEntry(db.Model):
    shift_id = db.Column(db.Integer, db.ForeignKey('shift.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    checked_in = db.Column(db.Boolean, nullable=False, default=False)
    missing_others = db.Column(db.Boolean, nullable=False, default=False)

"""
class TrainingSession(Shift):
    pass
"""

