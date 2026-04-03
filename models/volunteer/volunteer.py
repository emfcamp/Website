from collections import defaultdict
from typing import TYPE_CHECKING

from flask_login import UserMixin
from sqlalchemy import Column, ForeignKey, Integer, Table, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from main import db

from .. import BaseModel
from .shift import ShiftEntry, ShiftEntryState

if TYPE_CHECKING:
    from ..user import User
    from .role import Role, RoleAdmin, Team

__all__ = [
    "Volunteer",
    "VolunteerRoleInterest",
    "VolunteerRoleTraining",
]

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
    """A volunteer, which is mapped 1:1 to a website :class:`User`."""

    __tablename__ = "volunteer"
    __versioned__: dict[str, str] = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    nickname: Mapped[str | None]
    banned: Mapped[bool] = mapped_column(default=False)
    volunteer_phone: Mapped[str | None]
    volunteer_email: Mapped[str | None]
    over_18: Mapped[bool] = mapped_column(default=False)
    allow_comms_during_event: Mapped[bool] = mapped_column(default=False)

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))

    #: The website user object for this volunteer
    user: Mapped["User"] = relationship(back_populates="volunteer")

    #: Roles a volunteer is interested in performing
    interested_roles: Mapped[list["Role"]] = relationship(
        back_populates="interested_volunteers",
        secondary=VolunteerRoleInterest,
        lazy="dynamic",
    )

    #: Roles a volunteer has been trained to perform
    trained_roles: Mapped[list["Role"]] = relationship(
        back_populates="trained_volunteers",
        secondary=VolunteerRoleTraining,
        lazy="dynamic",
    )

    volunteer_admin_roles: Mapped[list["RoleAdmin"]] = relationship(
        back_populates="volunteer", cascade="all, delete-orphan"
    )

    administered_teams: Mapped[list["Team"]] = relationship(
        "Team", secondary="volunteer_team_admin", back_populates="admins"
    )

    def __repr__(self):
        return f"<Volunteer {self.__str__()}>"

    def __str__(self):
        return f"{self.user.name} <{self.user.email}>"

    def completed_shift(self, role):
        shifts = ShiftEntry.query.filter(
            ShiftEntry.shift.has(role=role),
            ShiftEntry.user == self.user,
            ShiftEntry.state == ShiftEntryState.COMPLETED,
        ).all()
        return bool(shifts)

    @classmethod
    def get_by_id(cls, id):
        return cls.query.get_or_404(id)

    @classmethod
    def get_by_email(cls, email_address: str) -> "Volunteer | None":
        return db.session.scalar(select(cls).where(cls.volunteer_email == email_address))

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

    @property
    def administered_role_ids(self) -> set[int]:
        """Role IDs this user can administer, combining direct role admin and team admin."""
        role_ids = {ra.role_id for ra in self.volunteer_admin_roles}
        for team in self.administered_teams:
            role_ids.update(r.id for r in team.roles)
        return role_ids

    @property
    def administered_team_ids(self) -> set[int]:
        """Team IDs this user can administer."""
        return {t.id for t in self.administered_teams}

    @property
    def is_volunteer_admin(self) -> bool:
        return bool(self.volunteer_admin_roles or self.administered_teams)


"""
class Messages(db.Model):
    from_user_id: Mapped[int] = mapped_column(ForeignKey('user.id'))
    to_user_id: Mapped[int] = mapped_column(ForeignKey('user.id'))
    sent: Mapped[datetime | None]
    text: Mapped[str]
    is_read: Mapped[bool] = mapped_column(default=False)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey('user.id'))
"""
