"""
ProposalAttribute – key/value store of additional information associated with
a Proposal (e.g. workshop capacity, equipment required)
"""

from datetime import datetime

from main import db
from .. import BaseModel


class ProposalAttribute(BaseModel):
    __versioned__ = {}
    __tablename__ = "proposal_attribute"

    id = db.Column(db.Integer, primary_key=True)
    proposal_item_id = db.Column(
        db.Integer, db.ForeignKey("proposal.id", nullable=False)
    )

    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow
    )

    key = db.Column(db.string, nullable=False, index=True)
    value = db.Column(db.string)
