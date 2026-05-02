"""
Round

The round model exists to store information about a round close
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import BaseModel, naive_utcnow
from .cfp import Proposal, ProposalType


class ProposalRound(BaseModel):
    __tablename__ = "proposal_round"
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposal.id"), primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("round.id"), primary_key=True)
    vote_count: Mapped[int]
    score: Mapped[float]
    outcome: Mapped[str]

    round: Mapped["Round"] = relationship(back_populates="proposal_rounds")  # noqa UP037
    proposal: Mapped[Proposal] = relationship(back_populates="proposal_rounds")


class Round(BaseModel):
    __tablename__ = "round"

    id: Mapped[int] = mapped_column(primary_key=True)

    created: Mapped[datetime] = mapped_column(default=naive_utcnow)
    modified: Mapped[datetime] = mapped_column(default=naive_utcnow, onupdate=naive_utcnow)

    proposal_type: Mapped[ProposalType]
    minimum_votes: Mapped[int]
    minimum_score: Mapped[float]

    proposal_rounds: Mapped[list[ProposalRound]] = relationship(back_populates="round")
