"""
ContentTypeDefinition - we need a way to track which content types we have
defined and which attributes they expect to exist

ContentTypeFieldDefinition - defines a field used by a content type.

We assume that all proposal types will have a corresponding schedule item type.
"""

from main import db
from .. import BaseModel


class ContentTypeDefinition(BaseModel):
    __tablename__ = "content_type_definition"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, index=True)

    fields = db.relationship("ContentTypeFieldDefinition", backref="type")

    def __init__(self, name: str):
        self.name = name


class ContentTypeFieldDefinition(BaseModel):
    __tablename__ = "content_type_field_definition"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    display_name = db.Column(db.String, nullable=False)

    # if default is Null/None it is a required field
    default = db.Column(db.String, nullable=True)

    type_id = db.Column(
        db.Integer,
        db.ForeignKey("content_type_definition.id"),
        nullable=False,
        index=True,
    )

    def __init__(
        self,
        content_type: ContentTypeDefinition,
        name: str,
        display_name: str | None = None,
        default: str | None = None,
    ):
        self.type_id = content_type.id
        self.name = name.lower()

        if display_name is None:
            self.display_name = name.lower()
        else:
            self.display_name = display_name

        if default is not None:
            self.default = default

    @property
    def is_required(self):
        return self.default is None
