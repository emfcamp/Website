from user import User

from main import db

class Volunteer(User):
    __table_name__ = 'volunteer'

    __versioned__ = {}

    planned_arrival = db.Column(db.DateTime)
    planned_departure = db.Column(db.DateTime)
    nickname = db.Column(db.String)
    missing_shifts_opt_in = db.Column(db.Boolean, nullable=False, default=False)
    banned = db.Column(db.Boolean, nullable=False, default=False)
    volunteer_phone = db.Column(db.String, nullable=False)
    volunteer_email = db.Column(db.String)

"""
class Messages(db.Model):
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sent = db.Column(db.DateTime)
    text = db.Column(db.String)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    shift_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
"""

