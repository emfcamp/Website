from collections import defaultdict
from sqlalchemy.orm import backref
from flask_login import UserMixin

from main import db
from .. import BaseModel

from . import ShiftEntry


# This effectively records the roles that a volunteer is interested in
VolunteerRoleInterest = db.Table(
    "volunteer_role_interest",
    db.Model.metadata,
    db.Column("volunteer_id", db.Integer, db.ForeignKey("volunteer.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("volunteer_role.id"), primary_key=True),
)


# Which roles has the volunteer been trained for
VolunteerRoleTraining = db.Table(
    "volunteer_role_training",
    db.Model.metadata,
    db.Column("volunteer_id", db.Integer, db.ForeignKey("volunteer.id"), primary_key=True),
    db.Column("role_id", db.Integer, db.ForeignKey("volunteer_role.id"), primary_key=True),
)


class Volunteer(BaseModel, UserMixin):
    __table_name__ = "volunteer"
    __versioned__: dict = {}

    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String)
    banned = db.Column(db.Boolean, nullable=False, default=False)
    volunteer_phone = db.Column(db.String)
    volunteer_email = db.Column(db.String)
    over_18 = db.Column(db.Boolean, nullable=False, default=False)
    allow_comms_during_event = db.Column(db.Boolean, nullable=False, default=False)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    user = db.relationship("User", backref=backref("volunteer", uselist=False))

    interested_roles = db.relationship(
        "Role",
        backref="interested_volunteers",
        secondary=VolunteerRoleInterest,
        lazy="dynamic",
    )
    trained_roles = db.relationship(
        "Role",
        backref="trained_volunteers",
        secondary=VolunteerRoleTraining,
        lazy="dynamic",
    )

    def __repr__(self):
        return f"<Volunteer {self.__str__()}>"

    def __str__(self):
        return f"{self.user.name} <{self.user.email}>"

    def completed_shift(self, role):
        shifts = ShiftEntry.query.filter(
            ShiftEntry.shift.has(role=role),
            ShiftEntry.user == self.user,
            ShiftEntry.state == "completed",
        ).all()
        return bool(shifts)

    @classmethod
    def get_by_id(cls, id):
        return cls.query.get_or_404(id)

    @classmethod
    def get_for_user(cls, user):
        return cls.query.filter_by(user_id=user.id).first()

    @classmethod
    def get_all(cls):
        return cls.query.order_by(Volunteer.nickname).all()

    @classmethod
    def get_export_data(cls):
        hist = defaultdict(lambda: 0)
        for v in Volunteer.get_all():
            hist[len(v.user.shift_entries)] += 1
        return {"public": {"shift_histogram": hist}}


"""
class Messages(db.Model):
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sent = db.Column(db.DateTime)
    text = db.Column(db.String)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    shift_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
"""
