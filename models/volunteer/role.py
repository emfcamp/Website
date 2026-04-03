from itertools import groupby
from operator import itemgetter
from typing import TYPE_CHECKING, Any

from markdown import markdown
from markupsafe import Markup
from sqlalchemy import Column, ForeignKey, Integer, Table, Text, func, select
from sqlalchemy.orm import Mapped, mapped_column, noload, relationship

from main import db, get_or_404

from .. import BaseModel
from .volunteer import VolunteerRoleInterest, VolunteerRoleTraining

if TYPE_CHECKING:
    from .shift import Shift
    from .volunteer import Volunteer

__all__ = [
    "Role",
    "RoleAdmin",
    "RolePermission",
    "Team",
]


class Role(BaseModel):
    """A role which a volunteer can perform."""

    __tablename__ = "volunteer_role"
    id: Mapped[int] = mapped_column(primary_key=True)
    #: The name used to present a role. Should be kept short as it gets used in lists.
    name: Mapped[str] = mapped_column(unique=True, index=True)
    #: A brief summary of the role
    description: Mapped[str | None]
    #: A longer description of the role, supports Markdown.
    full_description_md: Mapped[str | None] = mapped_column(Text)
    #: A link to some instructions on how to perform the role.
    instructions_url: Mapped[str | None]
    #: Things to know for the shift
    role_notes: Mapped[str | None]
    #: Whether the role is restricted to over-18s (e.g. bar shifts)
    over_18_only: Mapped[bool] = mapped_column(default=False)
    #: Whether the role requires training to perform
    requires_training: Mapped[bool] = mapped_column(default=False)

    team_id: Mapped[int] = mapped_column(ForeignKey("volunteer_team.id"))
    #: The team this role is under
    team: Mapped["Team"] = relationship(back_populates="roles", lazy="joined")

    #: Admins for this role
    admins: Mapped[list["RoleAdmin"]] = relationship(back_populates="role", cascade="all, delete-orphan")
    #: Shifts
    shifts: Mapped[list["Shift"]] = relationship(back_populates="role")

    #: Volunteers who are interested in this role
    interested_volunteers: Mapped[list["Volunteer"]] = relationship(
        back_populates="interested_roles", secondary=VolunteerRoleInterest
    )
    #: Volunteers who are trained for this role
    trained_volunteers: Mapped[list["Volunteer"]] = relationship(
        back_populates="trained_roles", secondary=VolunteerRoleTraining
    )

    @property
    def team_name(self) -> str:
        return self.team.name

    @property
    def team_slug(self) -> str:
        return self.team.slug

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

    #: Render the full description as Markdown.
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
    def from_dict(cls, data: dict[str, Any]) -> "Role":
        role = Role.get_by_name(data["name"]) or Role(name=data["name"])
        role.name = data["name"]
        role.description = data["description"]
        role.full_description_md = data.get("full_description_md", "")
        role.role_notes = data.get("role_notes")
        role.over_18_only = data.get("over_18_only", False)
        role.requires_training = data.get("requires_training", False)
        return role

    @classmethod
    def get_export_data(cls):
        from . import Shift, ShiftEntry

        shift_counts_q = (
            select(
                Shift.role_id,
                ShiftEntry.user_id,
                func.count(ShiftEntry.shift_id).label("shift_count"),
            )
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
            .options(noload(Role.team))
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


class Team(BaseModel):
    """A team that can have a number of volunteer roles attached."""

    __tablename__ = "volunteer_team"

    id: Mapped[int] = mapped_column(primary_key=True)

    #: The name used to present a role. Should be kept short as it gets used in lists.
    name: Mapped[str] = mapped_column(unique=True)

    #: A stable identifier used for team specific functionality to avoid things
    #: breaking if the team name changes.
    slug: Mapped[str] = mapped_column(unique=True, index=True)

    #: Users who are admins for all roles within this team.
    admins: Mapped[list["Volunteer"]] = relationship(
        "Volunteer",
        secondary="volunteer_team_admin",
        back_populates="administered_teams",
    )

    #: Roles that sit under this team.
    roles: Mapped[list["Role"]] = relationship(back_populates="team")

    @classmethod
    def get_by_id(cls, id: int) -> "Team":
        return get_or_404(db, Team, id)

    @classmethod
    def get_by_slug(cls, slug: str) -> "Team | None":
        return db.session.scalar(select(cls).where(cls.slug == slug))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Team":
        team = cls.get_by_slug(data["slug"]) or cls(slug=data["slug"])
        team.name = data["name"]
        return team


class RolePermission(BaseModel):
    __versioned__: dict[str, str] = {}
    __tablename__ = "volunteer_role_permission"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, index=True)


class RoleAdmin(BaseModel):
    """Join table used to indicate a given volunteer has admin permissions for a role."""

    __tablename__ = "volunteer_role_admin"
    volunteer_id: Mapped[int] = mapped_column(ForeignKey("volunteer.id"), primary_key=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("volunteer_role.id"), primary_key=True)

    #: Volunteer to be an admin
    volunteer: Mapped["Volunteer"] = relationship(back_populates="volunteer_admin_roles")
    #: Role the user is an admin for
    role: Mapped[Role] = relationship(back_populates="admins")


VolunteerTeamAdmin = Table(
    "volunteer_team_admin",
    BaseModel.metadata,
    Column("volunteer_id", Integer, ForeignKey("volunteer.id"), primary_key=True),
    Column("team_id", Integer, ForeignKey("volunteer_team.id"), primary_key=True),
)


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
