"""
A proposed piece of content to be reviewed by the EMF team (this is what the
CfP form generates). Proposals now only track the review state - when a
proposal for a talk or workshop is accepted, a corresponding ScheduleItem
is created.
"""

import typing

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import BaseModel
from .type_definition import ContentTypeDefinition

if typing.TYPE_CHECKING:
    from .. import User


class NewProposal(BaseModel):
    __versioned__: dict = {}
    __tablename__ = "content_proposal"

    # Columns
    id: Mapped[int] = mapped_column(primary_key=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("content_type_definition.id"), index=True)

    # Relationships
    type: Mapped[ContentTypeDefinition] = relationship(back_populates="proposals")
    users_new: Mapped[list["User"]] = relationship(
        back_populates="proposals_new",
        secondary="content_user_proposal",
    )
