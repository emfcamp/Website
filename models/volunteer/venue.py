from typing import TYPE_CHECKING

from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import BaseModel

if TYPE_CHECKING:
    from .shift import Shift


class VolunteerVenue(BaseModel):
    __tablename__ = "volunteer_venue"
    id: Mapped[int] = mapped_column(primary_key=True)
    # TODO: shouldn't be nullable
    name: Mapped[str | None] = mapped_column(unique=True, index=True)
    mapref: Mapped[str | None] = mapped_column()

    shifts: Mapped[list["Shift"]] = relationship(back_populates="venue")

    def __repr__(self):
        return f"<VolunteerVenue {self.name}>"

    def __str__(self):
        return self.name

    def to_dict(self):
        return {"id": self.id, "name": self.name, "mapref": self.mapref}

    @classmethod
    def get_all(cls):
        return cls.query.order_by(VolunteerVenue.id).all()

    @classmethod
    def get_by_id(cls, id):
        return cls.query.get(id)

    @classmethod
    def get_by_name(cls, name):
        return cls.query.filter_by(name=name).one_or_none()
