from itertools import groupby
from operator import itemgetter
from main import db
from markdown import markdown
from markupsafe import Markup

from .. import BaseModel
from .volunteer import VolunteerRoleInterest, VolunteerRoleTraining


class Role(BaseModel):
    __tablename__ = "volunteer_role"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False, unique=True, index=True)
    description = db.Column(db.String)
    full_description_md = db.Column(db.Text)
    instructions_url = db.Column(db.String)
    # Things to know for the shift
    role_notes = db.Column(db.String)
    over_18_only = db.Column(db.Boolean, nullable=False, default=False)
    requires_training = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self):
        return "<VolunteerRole {0}>".format(self.name)

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
            db.select(Shift.role_id, ShiftEntry.user_id, db.func.count(ShiftEntry.shift_id).label("shift_count"))
            .select_from(ShiftEntry)
            .join(Shift)
            .group_by(Shift.role_id, ShiftEntry.user_id)
            .cte("shift_counts")
        )
        shift_histogram_q = (
            db.select(Role, shift_counts_q.c.shift_count, db.func.count(shift_counts_q.c.user_id))
            .select_from(Role)
            .outerjoin(shift_counts_q)
            .group_by(Role, shift_counts_q.c.shift_count)
            .order_by(Role.id)
        )

        interested_volunteers_q = (
            db.select(VolunteerRoleInterest.c.role_id, db.func.count())
            .select_from(VolunteerRoleInterest)
            .group_by(VolunteerRoleInterest.c.role_id)
        )
        interested_volunteers = {role_id: count for role_id, count in db.session.execute(interested_volunteers_q)}

        trained_volunteers_q = (
            db.select(VolunteerRoleTraining.c.role_id, db.func.count())
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
    __versioned__: dict = {}
    __tablename__ = "volunteer_role_permission"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, index=True)


class RoleAdmin(BaseModel):
    __tablename__ = "volunteer_role_admin"
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, primary_key=True
    )
    user = db.relationship("User", backref="volunteer_admin_roles")
    role_id = db.Column(
        db.Integer, db.ForeignKey("volunteer_role.id"), nullable=False, primary_key=True
    )
    role = db.relationship("Role", backref="admins")


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
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, index=True)

class RoleQuals(db.Model):
    __tablename__ = 'volunteer_role_qual'
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), primary_key=True)
    qual_id = db.Column(db.Integer, db.ForeignKey('qual.id'), primary_key=True)
    required = db.Column(db.Boolean, nullable=False, default=False)
    self_certified = db.Column(db.Boolean, nullable=False, default=False)

class UserQuals(db.Model):
    __tablename__ = 'user_role_qual'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    qual_id = db.Column(db.Integer, db.ForeignKey('qual.id'), primary_key=True)
"""
