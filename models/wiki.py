from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from main import NaiveDT, db
from models import BaseModel, naive_utcnow

if TYPE_CHECKING:
    from models.user import User

__all__ = ["WikiPage"]


class WikiPage(BaseModel):
    __tablename__ = "wiki_page"
    __versioned__: dict[str, str] = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True, index=True)
    title: Mapped[str]
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[NaiveDT] = mapped_column(default=naive_utcnow)
    updated_at: Mapped[NaiveDT] = mapped_column(default=naive_utcnow, onupdate=naive_utcnow)

    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), nullable=True)

    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    updated_by: Mapped[User | None] = relationship(foreign_keys=[updated_by_id])

    @classmethod
    def get_by_slug(cls, slug: str) -> WikiPage | None:
        return db.session.execute(select(cls).where(cls.slug == slug)).scalar_one_or_none()

    @classmethod
    def all_pages(cls) -> list[WikiPage]:
        return list(db.session.execute(select(cls).order_by(cls.title)).scalars())

    def __repr__(self) -> str:
        return f"<WikiPage slug={self.slug!r} title={self.title!r}>"
