"""
Call for Participation

This module deals with accepting content proposals from users and reviewing them
(manually or through anonymised review).

Once a CfP proposal is accepted, an item is created in the schedule.
"""

import dataclasses
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import (  # noqa: UP035
    TYPE_CHECKING,
    Any,
    Literal,
    Type,
    cast,
    get_args,
)

import sqlalchemy
from sqlalchemy import JSON, ForeignKey, UniqueConstraint, select
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.config import config
from main import NaiveDT, db

from .. import BaseModel, export_attr_counts, export_attr_edits, export_intervals, naive_utcnow
from ..product import ProductView, Voucher
from ..user import User
from .attributes import (
    Attributes,
    ProposalInstallationAttributes,
    ProposalPerformanceAttributes,
    ProposalTalkAttributes,
    ProposalWorkshopAttributes,
    ProposalYouthWorkshopAttributes,
    attributes_proxy,
    copy_common_attributes,
)
from .tagging import ProposalTag, Tag

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .round import ProposalRound


# This might be better as a StrEnum, but would require disallowing hyphens.
# Using literals does not trigger sqla's native_enum functionality, so
# this column remains a varchar, and does not generate an enum type.
# https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html#native-enums-and-naming
ProposalState = Literal[
    "new",
    "edit",
    "checked",
    "rejected",
    "anonymised",
    "anon-blocked",
    "manual-review",
    "reviewed",
    "accepted",
    "finalised",
    "withdrawn",
    "conduct-blocked",
]

PROPOSAL_STATE_TRANSITIONS: dict[ProposalState, set[ProposalState]] = {
    "new": {"accepted", "rejected", "withdrawn", "checked", "manual-review", "conduct-blocked"},
    "edit": {"accepted", "rejected", "withdrawn", "new", "conduct-blocked"},
    "checked": {"accepted", "rejected", "withdrawn", "anonymised", "anon-blocked", "edit", "conduct-blocked"},
    "rejected": {"accepted", "rejected", "withdrawn", "edit"},
    "anonymised": {
        "accepted",
        "rejected",
        "withdrawn",
        "manual-review",
        "reviewed",
        "edit",
        "conduct-blocked",
    },
    "anon-blocked": {"accepted", "rejected", "withdrawn", "reviewed", "edit", "conduct-blocked"},
    "manual-review": {"accepted", "rejected", "withdrawn", "new", "edit", "conduct-blocked"},
    "reviewed": {"accepted", "rejected", "withdrawn", "edit", "anonymised", "conduct-blocked"},
    "accepted": {"accepted", "rejected", "withdrawn", "edit", "finalised", "conduct-blocked"},
    "finalised": {"accepted", "rejected", "withdrawn", "conduct-blocked"},
    "withdrawn": {"accepted", "rejected", "withdrawn", "edit"},
}


# Most of these states are the same they're kept distinct for semantic reasons
# and because I'm lazy
VOTE_STATES = {
    "new": ["voted", "recused", "blocked"],
    "voted": ["resolved", "stale"],
    "recused": ["resolved", "stale"],
    "blocked": ["resolved", "stale"],
    "resolved": ["voted", "recused", "blocked"],
    "stale": ["voted", "recused", "blocked"],
}


class ProposalVoteStateException(Exception):
    pass


class InvalidVenueException(Exception):
    pass


class ReviewType(StrEnum):
    anonymous = "anonymous"
    manual = "manual"
    none = "none"


ProposalType = Literal[
    "talk",
    "performance",
    "workshop",
    "youthworkshop",
    "installation",
]


class Proposal(BaseModel):
    """A proposal for content submitted to us through the Call for Participation.

    Proposals can be reviewed manually or through the anonymous review system. If a proposal is accepted, a :class:`ScheduleItem` is created.
    """

    __tablename__ = "proposal"
    __versioned__: dict[str, Any] = {}

    id: Mapped[int] = mapped_column(primary_key=True)

    #: The type of the proposal. This controls how the proposal is handled.
    type: Mapped[ProposalType]

    #: The state of the proposal: where it is in the review process
    state: Mapped[ProposalState] = mapped_column(
        sqlalchemy.Enum(
            *get_args(ProposalState),
            native_enum=False,
        ),
        default="new",
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    anonymiser_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)

    title: Mapped[str]
    description: Mapped[str]
    duration: Mapped[str | None]

    # Other fields shared by all types
    needs_help: Mapped[bool] = mapped_column(default=False)
    equipment_required: Mapped[str | None]
    funding_required: Mapped[str | None]
    notice_required: Mapped[str | None]
    additional_info: Mapped[str | None]

    # Flags to be set by reviewers
    needs_money: Mapped[bool] = mapped_column(default=False)
    one_day: Mapped[bool] = mapped_column(default=False)
    rejected_email_sent: Mapped[bool] = mapped_column(default=False)
    still_considering_email_sent: Mapped[bool] = mapped_column(default=False, nullable=True)

    # We show the user when their proposal was submitted
    created: Mapped[datetime] = mapped_column(default=naive_utcnow)
    # Used for sorting in the CfP review page
    modified: Mapped[datetime] = mapped_column(default=naive_utcnow, onupdate=naive_utcnow)

    private_notes: Mapped[str | None]

    attributes_json: Mapped[dict[str, Any] | None] = mapped_column(
        "attributes", MutableDict.as_mutable(JSON), nullable=False, default=dict
    )

    #: The associated user, usually the person who submitted the proposal
    user: Mapped[User] = relationship(back_populates="proposals", foreign_keys=[user_id])
    messages: Mapped[list[ProposalMessage]] = relationship(back_populates="proposal")
    votes: Mapped[list[ProposalVote]] = relationship(back_populates="proposal")
    anonymiser: Mapped[User | None] = relationship(
        back_populates="anonymised_proposals", foreign_keys=[anonymiser_id]
    )
    _tags: Mapped[list[Tag]] = relationship(
        back_populates="proposals",
        cascade="all",
        secondary=ProposalTag,
    )
    proposal_rounds: Mapped[list["ProposalRound"]] = relationship(back_populates="proposal")  # noqa UP037

    schedule_item: Mapped[ScheduleItem | None] = relationship("ScheduleItem", back_populates="proposal")

    @property
    def tags(self) -> list[str]:
        return [t.tag for t in self._tags]

    @tags.setter
    def tags(self, tags: list[str]) -> None:
        found_tags = list(db.session.scalars(select(Tag).where(Tag.tag.in_(tags))))
        missing_tags = set(tags) - {t.tag for t in found_tags}
        if missing_tags:
            raise ValueError(f"Invalid tags {', '.join(missing_tags)}")
        self._tags = found_tags

    @classmethod
    def get_export_data(cls):
        return {}

    def get_unread_vote_note_count(self):
        return len([v for v in self.votes if not v.has_been_read])

    def get_total_vote_note_count(self):
        return len([v for v in self.votes if v.note and len(v.note) > 0])

    def get_unread_messages(self, user):
        return [m for m in self.messages if (not m.has_been_read and m.is_user_recipient(user))]

    def get_unread_count(self, user):
        return len(self.get_unread_messages(user))

    def mark_messages_read(self, user):
        messages = self.get_unread_messages(user)
        for msg in messages:
            msg.has_been_read = True
        return len(messages)

    def accept_proposal(self) -> None:
        self.state = "accepted"

        if not self.schedule_item:
            schedule_item = self.create_schedule_item()
            db.session.add(schedule_item)

        if self.type_info.grants_event_tickets:
            # The voucher code itself implements a 36-hour grace period, so we don't need to pad it here.
            voucher_expires_on_date = date.today() + timedelta(days=config.get("CFP_VOUCHER_EXPIRY_DAYS", 14))
            voucher_expires_at = cast(
                NaiveDT,
                datetime.combine(
                    voucher_expires_on_date,
                    time(),  # 00:00:00
                    tzinfo=None,
                ),
            )
            if self.user.cfp_voucher is None:
                # Issue a pseudo-voucher, which may have 0 capacity if the user already has 2 tickets.
                product_view = ProductView.get_by_name("speakers")
                if not product_view:
                    raise Exception("No 'speakers' product view created yet?")
                voucher = Voucher(
                    view=product_view,
                    email=self.user.email,
                    tickets_remaining=max(2 - self.user.adult_tickets_held(voucher=True), 0),
                    expiry=voucher_expires_at,
                )
                db.session.add(voucher)
                self.user.cfp_voucher = voucher
                log.info("Issuing user %s a CfP voucher until %s", self.user, voucher_expires_at)
            elif self.user.cfp_voucher.is_expired and self.user.cfp_voucher.tickets_remaining > 0:
                # Give the user an extension on their voucher. It's easier and
                # friendlier than writing explanatory text in the email.
                self.user.cfp_voucher.expiry = voucher_expires_at
                log.info(
                    "Extending user's %s CfP voucher to %s since a new proposal was accepted and their voucher has already expired",
                    self.user,
                    voucher_expires_at,
                )

    def create_schedule_item(self):
        # Create a schedule item using suitable defaults from the proposal
        schedule_item = ScheduleItem(
            type=self.type,
            state="unpublished",
            user=self.user,
            proposal=self,
            names=self.user.name,
            # pronouns
            title=self.title,
            description=self.description,
            # short_description
            official_content=True,
            default_video_privacy="public",
            # arrival_period
            # departure_period
            # available_times
            # contact_telephone
            # contact_eventphone
        )
        copy_common_attributes(self.attributes, schedule_item.attributes)

        if schedule_item.type_info.needs_occurrence:
            schedule_item.occurrences.append(
                Occurrence(
                    state="unscheduled",
                    occurrence_num=1,
                    video_privacy=schedule_item.default_video_privacy,
                )
            )

        return schedule_item

    @property
    def is_editable(self) -> bool:
        if self.state in {"new", "edit", "manual-review"}:
            return True
        return False

    @property
    def type_info(self) -> ProposalInfo:
        return PROPOSAL_INFOS[self.type]

    @property
    def human_type(self) -> str:
        return self.type_info.human_type

    @property
    def human_type_a(self) -> str:
        # Same as human_type but includes a/an
        return self.type_info.human_type_a

    @property
    def attributes(self) -> Attributes:
        if self.attributes_json is None:
            self.attributes_json = {}
        # if you cache this, you probably want to invalidate when self.type changes
        Proxy = attributes_proxy(self.type_info.attributes_cls, self.attributes_json)
        return Proxy(**self.attributes_json)

    @attributes.setter
    def attributes(self, value: Attributes) -> None:
        self.attributes_json = dataclasses.asdict(value)


## Disabled while we work out a better approach for this.
# validate_state_transitions(Proposal.state, PROPOSAL_STATE_TRANSITIONS)


@dataclass
class ProposalInfo:
    type: ProposalType
    human_type: str
    human_type_a: str
    review_type: ReviewType
    attributes_cls: Type[Attributes]  # noqa: UP006
    grants_event_tickets: bool = False


# Ordering here currently determines ordering in the admin UI,
# and maybe it shouldn't
PROPOSAL_INFOS: dict[ProposalType, ProposalInfo] = {
    "talk": ProposalInfo(
        type="talk",
        human_type="talk",
        human_type_a="a talk",
        review_type=ReviewType.anonymous,
        attributes_cls=ProposalTalkAttributes,
        grants_event_tickets=True,
    ),
    "performance": ProposalInfo(
        type="performance",
        human_type="performance",
        human_type_a="a performance",
        review_type=ReviewType.manual,
        attributes_cls=ProposalPerformanceAttributes,
    ),
    "workshop": ProposalInfo(
        type="workshop",
        human_type="workshop",
        human_type_a="a workshop",
        review_type=ReviewType.anonymous,
        attributes_cls=ProposalWorkshopAttributes,
        grants_event_tickets=True,
    ),
    "youthworkshop": ProposalInfo(
        type="youthworkshop",
        human_type="youth workshop",
        human_type_a="a youth workshop",
        review_type=ReviewType.manual,
        attributes_cls=ProposalYouthWorkshopAttributes,
        grants_event_tickets=True,
    ),
    "installation": ProposalInfo(
        # Installations might not have durations or Occurrences
        type="installation",
        human_type="installation",
        human_type_a="an installation",
        review_type=ReviewType.manual,
        attributes_cls=ProposalInstallationAttributes,
    ),
}


class ProposalMessage(BaseModel):
    __tablename__ = "proposal_message"

    id: Mapped[int] = mapped_column(primary_key=True)
    created: Mapped[datetime | None] = mapped_column(default=naive_utcnow)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposal.id"))

    message: Mapped[str]
    # Flags
    is_to_admin: Mapped[bool | None]
    has_been_read: Mapped[bool | None] = mapped_column(default=False)

    from_user: Mapped[User] = relationship(back_populates="messages_from")
    proposal: Mapped[Proposal] = relationship(back_populates="messages")

    def is_user_recipient(self, user: User) -> bool:
        """
        Because we want messages from proposers to be visible to all admin
        we need to infer the 'to' portion of the email, either it is
        to the proposer (from admin) or to admin (& from the proposer).

        Obviously if the proposer is also an admin this doesn't really work
        but equally they should know where to ask.
        """
        is_user_admin = user.has_permission("cfp_admin")
        is_user_proposer = user.id == self.proposal.user_id

        if is_user_proposer and not self.is_to_admin:
            return True

        # FIXME: this is wrong for an admin who is also the proposer, rename it
        if is_user_admin and self.is_to_admin:
            return True

        return False

    @classmethod
    def get_export_data(cls):
        count_attrs = ["has_been_read"]

        message_contents = (
            db.session.query(cls)
            .join(User)
            .with_entities(
                cls.proposal_id,
                User.email.label("from_user_email"),
                User.name.label("from_user_name"),
                cls.is_to_admin,
                cls.has_been_read,
                cls.message,
            )
            .order_by(cls.id)
        )

        data = {
            "private": {"message": message_contents},
            "public": {"messages": {"counts": export_attr_counts(cls, count_attrs)}},
            "tables": ["cfp_message", "cfp_message_version"],
        }
        data["public"]["messages"]["counts"]["created_day"] = export_intervals(
            db.session.query(cls), cls.created, "day", "YYYY-MM-DD"
        )

        return data


class ProposalVote(BaseModel):
    __tablename__ = "proposal_vote"
    __versioned__: dict[str, Any] = {"exclude": ["modified"]}

    # TODO: make (user_id, proposal_id) the PK instead?
    __table_args__ = (UniqueConstraint("user_id", "proposal_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposal.id"))
    state: Mapped[str]
    has_been_read: Mapped[bool] = mapped_column(default=False)

    vote: Mapped[int | None]  # Vote can be null for abstentions
    note: Mapped[str | None]

    # Used for sorting in the CfP review page
    modified: Mapped[datetime] = mapped_column(default=naive_utcnow, onupdate=naive_utcnow)

    user: Mapped[User] = relationship(back_populates="votes")
    proposal: Mapped[Proposal] = relationship(back_populates="votes")

    def __init__(self, user: User, proposal: Proposal):
        self.user = user
        self.proposal = proposal
        self.state = "new"

    def set_state(self, state):
        state = state.lower()
        if state not in VOTE_STATES:
            raise ProposalVoteStateException(f'"{state}" is not a valid state')

        if state not in VOTE_STATES[self.state]:
            raise ProposalVoteStateException(f'"{self.state}->{state}" is not a valid transition')

        self.state = state

    @classmethod
    def get_export_data(cls):
        count_attrs = ["state", "has_been_read", "vote"]
        edits_attrs = ["state", "vote", "note"]

        data = {
            "public": {
                "votes": {
                    "counts": export_attr_counts(cls, count_attrs),
                    "edits": export_attr_edits(cls, edits_attrs),
                }
            },
            "tables": ["cfp_vote", "cfp_vote_version"],
        }
        # FIXME
        # data["public"]["votes"]["counts"]["created_day"] = export_intervals(
        #    cls.query, cls.created, "day", "YYYY-MM-DD"
        # )

        return data


from .schedule import Occurrence, ScheduleItem

__all__ = [
    "PROPOSAL_INFOS",
    "Proposal",
    "ProposalInfo",
    "ProposalMessage",
    "ProposalState",
    "ProposalType",
    "ProposalVote",
    "ReviewType",
]
