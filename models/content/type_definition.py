"""
We want to be able to define content types via config rather than having them
hard-coded.

These are for things that will be only required for specific types. There may be
some functional use (e.g. for workshops: whether a type is ticketed) but it
should be limited.

The field definition requires that a default be set so that we can change type
with relative safety.
"""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from .. import BaseModel

if TYPE_CHECKING:
    from .proposal import NewProposal


class ContentTypeDefinition(BaseModel):
    __versioned__: dict = {}
    __tablename__ = "content_type_definition"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(unique=True, index=True)

    fields: Mapped[list["ContentTypeFieldDefinition"]] = relationship(back_populates="type")
    proposals: Mapped["NewProposal"] = relationship(back_populates="type")

    def __init__(self, name: str):
        self.name = name.lower()


class ContentTypeFieldDefinition(BaseModel):
    __versioned__: dict = {}
    __tablename__ = "content_type_field_definition"
    __tableargs__ = UniqueConstraint("name", "type_id")

    # Columns
    id: Mapped[int] = mapped_column(primary_key=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("content_type_definition.id"))

    name: Mapped[str]
    display_name: Mapped[str]
    default_value: Mapped[str]

    # Relationships
    type: Mapped["ContentTypeDefinition"] = relationship(back_populates="fields")

    def __init__(
        self,
        name: str,
        type: ContentTypeDefinition,
        default_value: str,
        display_name: str | None = None,
    ):
        self.name = name.lower()
        if display_name:
            self.display_name = display_name
        else:
            self.display_name = self.name.replace("-", " ").capitalize()

        self.type_id = type.id
        self.default_value = default_value

    @validates("default_value")
    def validate_default_value(self, _, default_value):
        if len(default_value) == 0:
            raise ValueError("default_value must not be empty")
        return default_value
