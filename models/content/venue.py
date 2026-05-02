from geoalchemy2 import Geometry, WKBElement
from geoalchemy2.shape import to_shape
from sqlalchemy import (
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from main import db

from .. import BaseModel
from ..village import Village
from .schedule import Occurrence, OccurrenceAllowedVenues, ScheduleItemType


class Venue(BaseModel):
    """
    A location where content can be scheduled.

    This can be an official talk stage, a village location, or any other
    place on site.
    """

    __tablename__ = "venue"
    __export_data__ = False
    __table_args__ = (UniqueConstraint("name", name="_venue_name_uniq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    village_id: Mapped[int | None] = mapped_column(ForeignKey("village.id"), default=None)
    name: Mapped[str]

    # Which type of schedule item are allowed to be scheduled in this venue.
    allowed_types: Mapped[list[ScheduleItemType]] = mapped_column(
        MutableList.as_mutable(ARRAY(db.String)),
        default=list,
    )

    # What type of schedule items are the default for this venue.
    # These are where the automatic scheduler will put items.
    default_for_types: Mapped[list[ScheduleItemType]] = mapped_column(
        MutableList.as_mutable(ARRAY(db.String)),
        default=list,
    )
    priority: Mapped[int] = mapped_column(default=0)
    capacity: Mapped[int | None]
    location: Mapped[WKBElement | None] = mapped_column(Geometry("POINT", srid=4326))
    allows_attendee_content: Mapped[bool | None]

    village: Mapped[Village] = relationship(
        back_populates="venues",
        primaryjoin="Village.id == Venue.village_id",
    )
    occurrences: Mapped[list[Occurrence]] = relationship(
        back_populates="scheduled_venue", foreign_keys=[Occurrence.scheduled_venue_id]
    )
    allowed_occurrences: Mapped[list[Occurrence]] = relationship(
        back_populates="allowed_venues",
        secondary=OccurrenceAllowedVenues,
    )

    def __repr__(self):
        return f"<Venue id={self.id}, name={self.name}>"

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
                "type": self.type,
            },
            "geometry": location.__geo_interface__,
        }

    @property
    def is_emf_venue(self):
        return bool(self.default_for_types)

    @classmethod
    def emf_venues(cls):
        return cls.query.filter(db.func.array_length(cls.default_for_types, 1) > 0).all()

    @classmethod
    def emf_venue_names_by_type(cls):
        """Return a map of proposal type to official EMF venues."""
        unnest = db.func.unnest(cls.default_for_types).table_valued()
        return {
            type: venue_names
            for venue_names, type in db.session.execute(
                db.select(db.func.array_agg(cls.name), unnest.column)
                .join(unnest, db.true())
                .group_by(unnest.column)
            )
        }

    @classmethod
    def get_by_name(cls, name):
        return cls.query.filter_by(name=name).one()

    @property
    def latlon(self):
        if self.location:
            loc = to_shape(self.location)
            return (loc.y, loc.x)
        if self.village and self.village.latlon:
            return self.village.latlon
        return None

    @property
    def map_link(self) -> str | None:
        if not self.latlon:
            return None
        lat, lon = self.latlon
        return f"https://map.emfcamp.org/#18.5/{lat}/{lon}/m={lat},{lon}"
