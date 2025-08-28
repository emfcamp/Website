from collections import defaultdict
from typing import TYPE_CHECKING

from flask_login import UserMixin
from sqlalchemy import Column, ForeignKey, Integer, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import BaseModel
from .shift import ShiftEntry

if TYPE_CHECKING:
    from ..user import User
    from .role import Role

# This effectively records the roles that a volunteer is interested in
VolunteerRoleInterest = Table(
    "volunteer_role_interest",
    BaseModel.metadata,
    Column("volunteer_id", Integer, ForeignKey("volunteer.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("volunteer_role.id"), primary_key=True),
)


# Which roles has the volunteer been trained for
VolunteerRoleTraining = Table(
    "volunteer_role_training",
    BaseModel.metadata,
    Column("volunteer_id", Integer, ForeignKey("volunteer.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("volunteer_role.id"), primary_key=True),
)


class Volunteer(BaseModel, UserMixin):
    __tablename__ = "volunteer"
    __versioned__: dict = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    nickname: Mapped[str | None] = mapped_column()
    banned: Mapped[bool] = mapped_column(default=False)
    volunteer_phone: Mapped[str | None] = mapped_column()
    volunteer_email: Mapped[str | None] = mapped_column()
    over_18: Mapped[bool] = mapped_column(default=False)
    allow_comms_during_event: Mapped[bool] = mapped_column(default=False)

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))

    user: Mapped["User"] = relationship(back_populates="volunteer")

    interested_roles: Mapped[list["Role"]] = relationship(
        back_populates="interested_volunteers",
        secondary=VolunteerRoleInterest,
        lazy="dynamic",
    )
    trained_roles: Mapped[list["Role"]] = relationship(
        back_populates="trained_volunteers",
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
        total_volunteers = 0  # this is just the sum of the histogram, but useful to have it separate
        for v in Volunteer.get_all():
            hist[len(v.user.shift_entries)] += 1
            total_volunteers += 1
        return {
            "public": {
                "shift_histogram": hist,
                "total_volunteers": total_volunteers,
            },
        }


"""
class Messages(db.Model):
    from_user_id: Mapped[int] = mapped_column(ForeignKey('user.id'))
    to_user_id: Mapped[int] = mapped_column(ForeignKey('user.id'))
    sent: Mapped[datetime | None] = mapped_column()
    text: Mapped[str] = mapped_column()
    is_read: Mapped[bool] = mapped_column(default=False)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey('user.id'))
"""
