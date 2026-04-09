from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import BaseModel

if TYPE_CHECKING:
    from .shift import Shift

__all__ = ["VolunteerVenue"]


class VolunteerVenue(BaseModel):
    """A location for a volunteering shift."""

    __tablename__ = "volunteer_venue"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    mapref: Mapped[str | None]

    shifts: Mapped[list["Shift"]] = relationship(back_populates="venue")

    def __repr__(self):
        return f"<VolunteerVenue {self.name}>"

    def __str__(self):
        return self.name

    def to_dict(self):
        return {"id": self.id, "slug": self.slug, "name": self.name, "mapref": self.mapref}

    @classmethod
    def get_all(cls):
        return cls.query.order_by(VolunteerVenue.id).all()

    @classmethod
    def get_by_id(cls, id):
        return cls.query.get(id)

    @classmethod
    def get_by_name(cls, name):
        return cls.query.filter_by(name=name).one_or_none()

    @classmethod
    def get_by_slug(cls, slug):
        return cls.query.filter_by(slug=slug).one_or_none()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VolunteerVenue":
        venue = cls.get_by_slug(data["slug"]) or cls(slug=data["slug"])
        venue.name = data["name"]
        venue.mapref = data["mapref"]
        return venue
