from __future__ import annotations
from typing import Optional
from sqlalchemy.ext.associationproxy import association_proxy

from geoalchemy2 import Geometry
from geoalchemy2.shape import to_shape
from sqlalchemy import Index
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
    location = db.Column(Geometry("POINT", srid=4326, spatial_index=False))

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

    @property
    def __geo_interface__(self):
        """GeoJSON-like representation of the object for the map."""
        if not self.location:
            return None

        location = to_shape(self.location)

        return {
            "type": "Feature",
            "properties": {
                "id": self.id,
                "name": self.name,
                "description": self.description,
                "url": self.url,
            },
            "geometry": location.__geo_interface__,
        }

    @property
    def latlon(self):
        if self.location:
            loc = to_shape(self.location)
            return (loc.y, loc.x)
        return None

    @property
    def map_link(self) -> Optional[str]:
        latlon = self.latlon
        if latlon:
            return "https://map.emfcamp.org/#18.5/%s/%s/m=%s,%s" % (latlon[0], latlon[1], latlon[0], latlon[1])
        return None


# I'm not entirely sure why we create this index separately but this is how
# it was done with the old MapObject stuff.
Index("ix_village_location", Village.location, postgresql_using="gist")


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
