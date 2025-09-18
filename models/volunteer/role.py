from itertools import groupby
from operator import itemgetter
from typing import TYPE_CHECKING

from markdown import markdown
from markupsafe import Markup
from sqlalchemy import ForeignKey, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from main import db

from .. import BaseModel
from .volunteer import Volunteer, VolunteerRoleInterest, VolunteerRoleTraining

if TYPE_CHECKING:
    from ..user import User
    from .shift import Shift

__all__ = [
    "Role",
    "RoleAdmin",
    "RolePermission",
]


class Role(BaseModel):
    __tablename__ = "volunteer_role"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)
    description: Mapped[str | None]
    full_description_md: Mapped[str | None] = mapped_column(Text)
    instructions_url: Mapped[str | None]
    # Things to know for the shift
    role_notes: Mapped[str | None]
    over_18_only: Mapped[bool] = mapped_column(default=False)
    requires_training: Mapped[bool] = mapped_column(default=False)

    admins: Mapped[list["RoleAdmin"]] = relationship(back_populates="role")
    shifts: Mapped[list["Shift"]] = relationship(back_populates="role")
    interested_volunteers: Mapped[list["Volunteer"]] = relationship(
        back_populates="interested_roles", secondary=VolunteerRoleInterest
    )
    trained_volunteers: Mapped[list["Volunteer"]] = relationship(
        back_populates="trained_roles", secondary=VolunteerRoleTraining
    )

    def __repr__(self):
        return f"<VolunteerRole {self.name}>"

    def __str__(self):
        return self.name

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "role_notes": self.role_notes,
            "requires_training": self.requires_training,
        }

    def full_description(self):
        content = self.full_description_md
        if content:
            return Markup(markdown(content, extensions=["markdown.extensions.nl2br"]))
        return ""

    @classmethod
    def get_by_name(cls, name):
        return cls.query.filter_by(name=name).one_or_none()

    @classmethod
    def get_by_id(cls, id):
        return cls.query.get_or_404(id)

    @classmethod
    def get_all(cls):
        return cls.query.order_by(Role.name).all()

    @classmethod
    def get_export_data(cls):
        from . import Shift, ShiftEntry

        shift_counts_q = (
            select(Shift.role_id, ShiftEntry.user_id, func.count(ShiftEntry.shift_id).label("shift_count"))
            .select_from(ShiftEntry)
            .join(Shift)
            .group_by(Shift.role_id, ShiftEntry.user_id)
            .cte("shift_counts")
        )
        shift_histogram_q = (
            select(Role, shift_counts_q.c.shift_count, func.count(shift_counts_q.c.user_id))
            .select_from(Role)
            .outerjoin(shift_counts_q)
            .group_by(Role, shift_counts_q.c.shift_count)
            .order_by(Role.id)
        )

        interested_volunteers_q = (
            select(VolunteerRoleInterest.c.role_id, func.count())
            .select_from(VolunteerRoleInterest)
            .group_by(VolunteerRoleInterest.c.role_id)
        )
        interested_volunteers = {
            role_id: count for role_id, count in db.session.execute(interested_volunteers_q)
        }

        trained_volunteers_q = (
            select(VolunteerRoleTraining.c.role_id, func.count())
            .select_from(VolunteerRoleTraining)
            .group_by(VolunteerRoleTraining.c.role_id)
        )
        trained_volunteers = {role_id: count for role_id, count in db.session.execute(trained_volunteers_q)}

        roles = {}
        for role, stats in groupby(db.session.execute(shift_histogram_q), itemgetter(0)):
            shift_histogram = {shifts: volunteers for _, shifts, volunteers in stats}
            roles[role.name] = {
                "shift_histogram": shift_histogram,
                "total_volunteers": sum(shift_histogram.values()),
                "interested_volunteers": interested_volunteers.get(role.id),
            }
            if role.requires_training:
                roles[role.name]["trained_volunteers"] = trained_volunteers.get(role.id)

        return {
            "public": {
                "roles": roles,
            },
        }


class RolePermission(BaseModel):
    __versioned__: dict[str, str] = {}
    __tablename__ = "volunteer_role_permission"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)


class RoleAdmin(BaseModel):
    __tablename__ = "volunteer_role_admin"
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("volunteer_role.id"), primary_key=True)

    user: Mapped["User"] = relationship(back_populates="volunteer_admin_roles")
    role: Mapped[Role] = relationship(back_populates="admins")


"""
Qualifications include:
 - Over 18
 - Bar training
 - Bar supervisor training
 - DBS check (reduces min required for a shift)
 - Checked into site
 - Phone validated

class Qual(db.Model):
    __tablename__ = 'volunteer_qual'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)

class RoleQuals(db.Model):
    __tablename__ = 'volunteer_role_qual'
    role_id: Mapped[int] = mapped_column(ForeignKey('role.id'), primary_key=True)
    qual_id: Mapped[int] = mapped_column(ForeignKey('qual.id'), primary_key=True)
    required: Mapped[bool] = mapped_column(default=False)
    self_certified: Mapped[bool] = mapped_column(default=False)

class UserQuals(db.Model):
    __tablename__ = 'user_role_qual'
    user_id: Mapped[int] = mapped_column(ForeignKey('user.id'), primary_key=True)
    qual_id: Mapped[int] = mapped_column(ForeignKey('qual.id'), primary_key=True)
"""
