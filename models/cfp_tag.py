from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, Integer, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

from main import db
from models.user import CFPReviewerTags, User

from . import BaseModel

if TYPE_CHECKING:
    from .cfp import Proposal

DEFAULT_TAGS = [
    "accessibility",
    "ai",
    "alternative",
    "arts",
    "coding",
    "comedy",
    "crafts",
    "demoscene",
    "diversity",
    "electronics",
    "engineering",
    "environment",
    "fabrication",
    "food and drink",
    "games",
    "hackspaces",
    "history",
    "infrastructure",
    "internet",
    "lgbtq",
    "maths",
    "medicine",
    "meetups",
    "music",
    "open source",
    "politics",
    "psychology",
    "radio and communications",
    "robotics",
    "science",
    "security",
    "society",
    "solarpunk",
    "trains",
]


ProposalTag = Table(
    "proposal_tag",
    BaseModel.metadata,
    Column("proposal_id", Integer, ForeignKey("proposal.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tag.id"), primary_key=True),
)


class Tag(BaseModel):
    __versioned__: dict[str, str] = {}
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    tag: Mapped[str] = mapped_column(unique=True)

    proposals: Mapped[list["Proposal"]] = relationship(secondary=ProposalTag)
    reviewers: Mapped[list[User]] = relationship(
        back_populates="cfp_reviewer_tags", secondary=CFPReviewerTags
    )

    def __init__(self, tag: str):
        self.tag = tag.strip().lower()

    def __str__(self):
        return self.tag

    def __repr__(self):
        return f"<Tag {self.id} '{self.tag}'>"

    @classmethod
    def serialise_tags(self, tag_list: list["Tag"]) -> str:
        return ",".join([str(t) for t in tag_list])

    @classmethod
    def parse_serialised_tags(cls, tag_str: str) -> list["Tag"]:
        res = []
        tag_list = [t.strip().lower() for t in tag_str]
        for tag_value in tag_list:
            if len(tag_value) == 0:
                continue
            tag = cls.get_by_value(tag_value)
            if tag:
                res.append(tag)
            else:
                res.append(Tag(tag_value))
        return res

    @classmethod
    def get_by_value(cls, value):
        return cls.query.filter_by(tag=value).one_or_none()

    @classmethod
    def get_export_data(cls):
        tag_proposals_q = db.select(Tag, db.func.count(Tag.id)).join(Tag.proposals).group_by(Tag)
        tag_reviewers_q = db.select(Tag, db.func.count(Tag.id)).join(Tag.reviewers).group_by(Tag)
        tags = {
            "proposals": {tag.tag: c for tag, c in db.session.execute(tag_proposals_q)},
            "reviewers": {tag.tag: c for tag, c in db.session.execute(tag_reviewers_q)},
        }
        return {
            "public": {"tags": tags},
            "tables": ["tag", "proposal_tag", "cfp_reviewer_tags"],
        }
