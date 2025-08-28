from __future__ import annotations

from typing import TYPE_CHECKING

from geoalchemy2 import Geometry, WKBElement
from geoalchemy2.shape import to_shape
from sqlalchemy import ForeignKey, Index
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.user import User

from . import BaseModel

if TYPE_CHECKING:
    from .cfp import Venue


class Village(BaseModel):
    __tablename__ = "village"
    __versioned__: dict = {}

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[str | None] = mapped_column()
    url: Mapped[str | None] = mapped_column()
    location: Mapped[WKBElement | None] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))

    village_memberships: Mapped[list[VillageMember]] = relationship(back_populates="village")
    requirements: Mapped[VillageRequirements] = relationship(back_populates="village")
    venues: Mapped[list[Venue]] = relationship(back_populates="village")
    members = association_proxy("village_memberships", "user")

    @classmethod
    def get_by_name(cls, name) -> Village | None:
        return cls.query.filter_by(name=name).one_or_none()

    @classmethod
    def get_by_id(cls, id) -> Village | None:
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
    def map_link(self) -> str | None:
        if not self.latlon:
            return None
        lat, lon = self.latlon
        return f"https://map.emfcamp.org/#18.5/{lat}/{lon}/m={lat},{lon}"

    @classmethod
    def get_export_data(cls):
        data = {
            "public": {
                "villages": {
                    v.id: {
                        "name": v.name,
                        "description": v.description,
                        "url": v.url,
                        "location": v.latlon,
                    }
                    for v in Village.query.all()
                }
            },
            "tables": ["village", "village_member", "village_requirements"],
            "private": {
                # Village contact/attendee counts are exported here to issue vouchers for the next event
                "village_info": {
                    v.id: {
                        "admin_emails": [u.email for u in v.admins()],
                        "predicted_attendees": v.requirements.num_attendees,
                    }
                    for v in Village.query.all()
                },
            },
        }

        return data


# I'm not entirely sure why we create this index separately but this is how
# it was done with the old MapObject stuff.
Index("ix_village_location", Village.location, postgresql_using="gist")


class VillageMember(BaseModel):
    __tablename__ = "village_member"

    id: Mapped[int] = mapped_column(primary_key=True)
    # We only allow one village per user. TODO: make this the primary key
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), unique=True)
    village_id: Mapped[int] = mapped_column(ForeignKey("village.id"))
    # TODO: probably shouldn't be nullable
    admin: Mapped[bool | None] = mapped_column(default=False)

    village: Mapped[list[Village]] = relationship(back_populates="village_memberships")
    user: Mapped[User] = relationship(back_populates="village_membership")

    def __repr__(self):
        return f"<VillageMember {self.user} member of {self.village}>"


class VillageRequirements(BaseModel):
    __tablename__ = "village_requirements"

    village_id: Mapped[int] = mapped_column(ForeignKey("village.id"), primary_key=True)
    village: Mapped[Village] = relationship(back_populates="requirements")

    num_attendees: Mapped[int | None]
    size_sqm: Mapped[int | None]

    power_requirements: Mapped[str | None]
    noise: Mapped[str | None]

    structures: Mapped[str | None]
