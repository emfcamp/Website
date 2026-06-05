from datetime import datetime

from geoalchemy2 import Geometry, WKBElement
from geoalchemy2.shape import to_shape
from sqlalchemy import (
    ForeignKey,
    UniqueConstraint,
    select,
)
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

    priority: Mapped[int] = mapped_column(default=0)
    capacity: Mapped[int | None]
    location: Mapped[WKBElement | None] = mapped_column(Geometry("POINT", srid=4326))

    #: Whether this venue allows *any* attendee to schedule content in it.
    #: This is only true for official venues which allow attendee content (e.g. bar, lounge)
    #: and is currently null for village stages (which allow content to be scheduled by their admins)
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

    time_blocks: Mapped[list[TimeBlock]] = relationship(back_populates="venue")

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
            },
            "geometry": location.__geo_interface__,
        }

    @property
    def is_official(self):
        return self.village_id is not None

    @classmethod
    def official_venues(cls):
        return list(db.session.scalars(select(Venue).where(Venue.village_id.is_(None))))

    @classmethod
    def get_by_name(cls, name):
        return db.session.query(cls).filter_by(name=name).one()

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


class TimeBlock(BaseModel):
    """A block of time allocated in a venue for scheduling official content.

    Villages can schedule content in their venues outside a TimeBlock, but all official content must be inside a TimeBlock.

    Constraints:
        - There can only be one TimeBlock active for a venue at any time.
        - Each TimeBlock can only allow one content type in it.
        - TimeBlocks cannot span 5am, when the scheduling day ends.
    """

    id: Mapped[int] = mapped_column(primary_key=True)
    venue_id: Mapped[int] = mapped_column(ForeignKey("venue.id"))

    #: The type of item which can be scheduled in this TimeBlock
    type: Mapped[ScheduleItemType]

    #: Whether this block should be considered by the automatic scheduler
    automatic: Mapped[bool]

    start: Mapped[datetime]
    end: Mapped[datetime]

    venue: Mapped[Venue] = relationship(back_populates="time_blocks")

    def __repr__(self):
        return f"<TimeBlock ({self.type}) for {self.venue.name}: {self.start} - {self.end}>"
