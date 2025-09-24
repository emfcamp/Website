"""
A proposed piece of content to be reviewed by the EMF team (this is what the
CfP form generates). Proposals now only track the review state - when a
proposal for a talk or workshop is accepted, a corresponding ScheduleItem
is created.
"""

from sqlalchemy import ForeignKey, UniqueConstraint, Table, Column, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import BaseModel, User, UserProposal
from .type_definition import ContentTypeDefinition


class Proposal(BaseModel):
    __versioned__: dict = {}
    __tablename__ = "content_proposal"

    # Columns
    id: Mapped[int] = mapped_column(primary_key=True)
    type_id: Mapped[int] = mapped_column(ForeignKey("content_type_definition.id"), index=True)

    # Relationships
    type: Mapped[ContentTypeDefinition] = relationship(back_populates="proposals")
    # users: Mapped[list[User]] = relationship(
    #     primaryjoin=(UserProposal.c.proposal_id == id),
    #     back_populates="proposals", secondary=UserProposal
    # )
