from main import db
from markdown import markdown
from markupsafe import Markup

from .. import BaseModel


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


class RolePermission(BaseModel):
    __versioned__: dict = {}
    __tablename__ = "volunteer_role_permission"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, index=True)


class RoleAdmin(BaseModel):
    __tablename__ = "volunteer_role_admin"
    __versioned__: dict = {}
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
