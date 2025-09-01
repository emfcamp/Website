"""
We want to be able to define content types via config rather than having them
hard-coded.

These are for things that will be only required for specific types. There may be
some functional use (e.g. for workshops: whether a type is ticketed) but it
should be limited.
"""

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import BaseModel


class ContentTypeDefinition(BaseModel):
    __versioned__: dict = {}
    __tablename__ = "content_type_definition"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(unique=True, index=True)

    fields: Mapped[list["ContentTypeFieldDefinition"]] = relationship(back_populates="type")

    def __init__(self, name: str):
        self.name = name.lower()


class ContentTypeFieldDefinition(BaseModel):
    __versioned__: dict = {}
    __tablename__ = "content_type_field_definition"
    __tableargs__ = UniqueConstraint("name", "type_id")

    id: Mapped[int] = mapped_column(primary_key=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("content_type_definition.id"))

    # name: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    display_name: Mapped[str]

    default: Mapped[str | None] = mapped_column(default=None)

    type: Mapped[ContentTypeDefinition] = relationship(back_populates="fields")

    def __init__(
        self,
        name: str,
        type: ContentTypeDefinition,
        display_name: str | None = None,
        default: str | None = None,
    ):
        self.name = name.lower()
        if display_name:
            self.display_name = display_name
        else:
            self.display_name = self.name.replace("-", " ").capitalize()

        self.type_id = type.id

        if default is not None:
            self.default = default
