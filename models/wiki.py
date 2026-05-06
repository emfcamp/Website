from __future__ import annotations

from sqlalchemy import Text, select
from sqlalchemy.orm import Mapped, mapped_column

from main import db
from models import BaseModel

__all__ = ["WikiPage"]


class WikiPage(BaseModel):
    __tablename__ = "wiki_page"
    __versioned__: dict[str, str] = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(unique=True, index=True)
    title: Mapped[str]
    content: Mapped[str] = mapped_column(Text, default="")

    @classmethod
    def get_by_slug(cls, slug: str) -> WikiPage | None:
        return db.session.execute(select(cls).where(cls.slug == slug)).scalar_one_or_none()

    @classmethod
    def all_pages(cls) -> list[WikiPage]:
        return list(db.session.execute(select(cls).order_by(cls.title)).scalars())

    def __repr__(self) -> str:
        return f"<WikiPage slug={self.slug!r} title={self.title!r}>"
