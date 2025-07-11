"""
Proposal – a proposed piece of content to be reviewed by the EMF team (this is
what the CfP form generates). Proposals now only track the review state - when
a proposal for a talk or workshop is accepted, a corresponding ScheduleItem
is created.
"""

from datetime import datetime

from main import db
from ..cfp_tag import (
    ProposalTag,
)  # fixme copy into directory & make filename/classname match
from .. import BaseModel


UserProposal = db.Table(
    "user_proposal",
    BaseModel.metadata,
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column(
        "proposal_id",
        db.Integer,
        db.ForeignKey("proposal.id"),
        primary_key=True,
        index=True,
    ),
)


class Proposal(BaseModel):
    # FIXME remove _v2
    __tablename__ = "proposal_v2"

    id = db.Column(db.Integer, primary_key=True)
    users = db.relationship(
        "User", secondary=UserProposal, backref=db.backref("proposals")
    )

    type = db.Column(db.string, nullable=False)
    state = db.Column(db.string, nullable=False, default="new")

    title = db.Column(db.string, nullable=False)
    description = db.Column(db.string, nullable=False)

    needs_money = db.Column(db.Boolean, nullable=False, default=False)
    needs_help = db.Column(db.Boolean, nullable=False, default=False)
    private_notes = db.Column(db.string)

    tags = db.relationship(
        "Tag",
        backref="proposals",
        cascade="all",
        secondary=ProposalTag,
    )

    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow
    )

    has_rejected_email = db.Column(db.Boolean, nullable=False, default=False)

    schedule_item = db.relationship("ScheduleItem", backref="proposal")

    messages = db.relationship("CFPMessage", backref="proposal")
    votes = db.relationship("CFPVotes", backref="proposal")
