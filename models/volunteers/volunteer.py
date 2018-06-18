from user import User

from main import db

class Volunteer(User):
    # User has phone
    planned_arrival = db.Column(db.DateTime)
    planned_departure = db.Column(db.DateTime)
    nickname = db.Column(db.String)
    shift_email_opt_in = db.Column(db.Boolean, nullable=False)
    """
    other contact methods (DECT, second phone, etc)?
    age?
    dbs_check?
    checked_in
    api_key?
    """


class Messages(db.Model):
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sent = db.Column(db.DateTime)
    text = db.Column(db.String)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    shift_id = db.Column(db.Integer, db.ForeignKey('user.id'))

