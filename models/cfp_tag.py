from main import db
import sqlalchemy
from . import BaseModel


class Tag(BaseModel):
    __versioned__: dict = {}
    __tablename__ = "tag"

    id = db.Column(db.Integer, primary_key=True)
    tag = db.Column(db.String, nullable=False, unique=True)

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
        tag_list = [t.strip().lower() for t in tag_str.split(",")]
        for tag_value in tag_list:
            if len(tag_value) == 0:
                continue
            tag = cls.query.filter_by(tag=tag_value).one_or_none()
            if tag:
                res.append(tag)
            else:
                res.append(Tag(tag_value))
        return res


ProposalTag: sqlalchemy.Table = db.Table(
    "proposal_tag",
    BaseModel.metadata,
    db.Column(
        "proposal_id", db.Integer, db.ForeignKey("proposal.id"), primary_key=True
    ),
    db.Column("tag_id", db.Integer, db.ForeignKey("tag.id"), primary_key=True),
)
