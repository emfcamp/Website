"""
Lightning talk

This exists as its own thing as they're sub-elements of an occurrence of a
lightning talk schedule item
"""

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import BaseModel
from ..user import User

if TYPE_CHECKING:
    from .schedule import Occurrence


class LightningTalk(BaseModel):
    __tablename__ = "lightning_talk"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurrence_id: Mapped[int] = mapped_column(ForeignKey("occurrence.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))

    title: Mapped[str]
    description: Mapped[str | None]
    slide_link: Mapped[str | None]

    occurrence: Mapped[Occurrence] = relationship(
        "Occurrence", back_populates="lightning_talks", foreign_keys=[occurrence_id]
    )
    user: Mapped[User] = relationship(back_populates="lightning_talks", foreign_keys=[user_id])
