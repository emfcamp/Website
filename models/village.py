from __future__ import annotations
from typing import Optional

from sqlalchemy.ext.associationproxy import association_proxy

from main import db
from models.user import User
from . import BaseModel


class Village(BaseModel):
    __tablename__ = "village"
    __versioned__: dict = {}

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String, nullable=False, unique=True)
    description = db.Column(db.String)
    url = db.Column(db.String)

    village_memberships = db.relationship("VillageMember", back_populates="village")
    members = association_proxy("village_memberships", "user")

    @classmethod
    def get_by_name(cls, name) -> Optional[Village]:
        return cls.query.filter_by(name=name).one_or_none()

    @classmethod
    def get_by_id(cls, id) -> Optional[Village]:
        return cls.query.filter_by(id=id).one_or_none()

    def admins(self) -> list[User]:
        return [m.user for m in self.village_memberships if m.admin]

    def __repr__(self):
        return f"<Village '{self.name}' (id: {self.id})>"


class VillageMember(BaseModel):
    __tablename__ = "village_member"

    id = db.Column(db.Integer, primary_key=True)
    # We only allow one village per user. TODO: make this the primary key
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False
    )
    village_id = db.Column(db.Integer, db.ForeignKey("village.id"), nullable=False)
    admin = db.Column(db.Boolean, default=False)

    village = db.relationship(
        "Village", back_populates="village_memberships", uselist=False
    )
    user = db.relationship("User", back_populates="village_membership", uselist=False)

    def __repr__(self):
        return f"<VillageMember {self.user} member of {self.village}>"


class VillageRequirements(BaseModel):
    __tablename__ = "village_requirements"

    village_id = db.Column(db.Integer, db.ForeignKey("village.id"), primary_key=True)
    village = db.relationship(
        "Village", backref=db.backref("requirements", uselist=False)
    )

    num_attendees = db.Column(db.Integer)
    size_sqm = db.Column(db.Integer)

    power_requirements = db.Column(db.String)
    noise = db.Column(db.String)

    structures = db.Column(db.String)
