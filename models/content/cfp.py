"""
Call for Participation

This module deals with accepting content proposals from users and reviewing them
(manually or through anonymised review).

Once a CfP proposal is accepted, an item is created in the schedule.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import (  # noqa: UP035
    Any,
    Literal,
    Type,
    get_args,
)

import sqlalchemy
from sqlalchemy import JSON, ForeignKey, UniqueConstraint, select
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column, relationship

from main import db

from .. import BaseModel, export_attr_counts, export_attr_edits, export_intervals, naive_utcnow
from ..user import User
from . import validate_state_transitions
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
        # FIXME
        # count_attrs = [
        #    "needs_help",
        #    "needs_money",
        #    "needs_laptop",
        #    "one_day",
        #    "notice_required",
        #    "video_privacy",
        #    "state",
        # ]

        # edits_attrs = [
        #    "published_title",
        #    "published_description",
        #    "duration",
        #    "equipment_required",
        #    "funding_required",
        #    "additional_info",
        #    "notice_required",
        #    "needs_help",
        #    "needs_money",
        #    "one_day",
        #    "rejected_email_sent",
        #    "published_names",
        #    "published_pronouns",
        #    "arrival_period",
        #    "departure_period",
        #    "contact_eventphone",
        #    "contact_telephone",
        #    "video_privacy",
        #    "needs_laptop",
        #    "available_times",
        #    "participant_count",
        #    "participant_cost",
        #    "size",
        #    "grant_requested",
        #    "age_range",
        #    "participant_equipment",
        # ]

        # proposals = cls.query.with_entities(
        #    cls.id,
        #    cls.title,
        #    cls.description,
        #    # cls.favourite_count,  # don't care about performance here
        #    cls.duration,
        #    cls.notice_required,
        #    cls.needs_money,
        #    # cls.available_times,
        #    # cls.allowed_times,
        #    # cls.arrival_period,
        #    # cls.departure_period,
        #    # cls.needs_laptop,
        #    # cls.video_privacy,
        # ).order_by(cls.id)

        # FIXME
        # if cls.__name__ == "WorkshopProposal":
        #    proposals = proposals.add_columns(cls.participant_count, cls.participant_cost, cls.age_range)
        # elif cls.__name__ == "InstallationProposal":
        #    proposals = proposals.add_columns(cls.size, cls.grant_requested)
        # elif cls.__name__ == "YouthWorkshopProposal":
        #    proposals = proposals.add_columns(
        #        cls.participant_count, cls.participant_cost, cls.age_range, cls.participant_equipment
        #    )

        # Some unaccepted proposals have scheduling data, but we shouldn't need to keep that
        # accepted_columns = (
        #    User.name,
        #    User.email,
        #    cls.published_names,
        #    cls.published_pronouns,
        #    cls.scheduled_time,
        #    cls.scheduled_duration,
        #    Venue.name,
        # )
        # accepted_proposals = (
        #    proposals.filter(cls.state.in_({"accepted", "finalised"}))
        #    .outerjoin(cls.scheduled_venue)
        #    .join(cls.user)
        #    .add_columns(*accepted_columns)
        # )

        # other_proposals = proposals.filter(~cls.state.in_({"accepted", "finalised"}))

        # FIXME schedule_items
        # user_favourites = (
        #    cls.query.filter(cls.state == "accepted")
        #    .join(cls.favourites)
        #    .with_entities(User.id.label("user_id"), cls.id)
        #    .order_by(User.id)
        # )

        # anon_favourites = []
        # for user_id, proposals in groupby(user_favourites, lambda r: r.user_id):
        #    anon_favourites.append([p.id for p in proposals])
        # anon_favourites.sort()

        # FIXME: get rid of this
        # if cls.__name__ == "LightningTalkScheduleItem":
        #    # Lightning talks don't usually get accepted
        #    states_to_export = ["accepted", "new"]
        #    columns_to_export = [
        #        # Use the submitted fields directly
        #        cls.title.label("published_title"),
        #        cls.description.label("published_description"),
        #        User.name.label("names"),
        #        # We omit fields that we don't have since they didn't go through CfP:
        #        # pronouns
        #        # video_privacy
        #        # scheduled_time
        #        # scheduled_duration
        #        # venue
        #        # venue_village_id
        #        # Lightning Talk specific fields:
        #        cls.session,
        #        cls.slide_link,
        #    ]
        # else:
        #    states_to_export = ["accepted"]
        #    columns_to_export = [
        #        cls.published_title,
        #        cls.published_description,
        #        cls.published_names.label("names"),
        #        cls.published_pronouns.label("pronouns"),
        #        cls.video_privacy,
        #        cls.scheduled_time,
        #        cls.scheduled_duration,
        #        Venue.name.label("venue"),
        #        Village.id.label("venue_village_id"),
        #    ]

        # exported_public = (
        #    cls.query.filter(cls.state.in_(states_to_export))
        #    .outerjoin(cls.scheduled_venue)
        #    .outerjoin(Venue.village)
        #    .with_entities(*columns_to_export)
        # )

        # favourite_counts = [p.favourite_count for p in proposals]

        # data = {
        #    "private": {
        #        "proposals": {
        #            "accepted_proposals": accepted_proposals,
        #            "other_proposals": other_proposals,
        #        },
        #        "favourites": anon_favourites,
        #    },
        #    "public": {
        #        "proposals": {
        #            "counts": export_attr_counts(cls, count_attrs),
        #            "edits": export_attr_edits(cls, edits_attrs),
        #            # This is still called accepted, but might not 'just' be accepted (e.g. Lightning Talks)
        #            "accepted": exported_public,
        #        },
        #        # "favourites": {"counts": bucketise(favourite_counts, [0, 1, 10, 20, 30, 40, 50, 100, 200])},
        #    },
        #    "tables": [
        #        "proposal",
        #        "proposal_version",
        #        "favourite_proposal",
        #        "favourite_proposal_version",
        #    ],
        # }
        # data["public"]["proposals"]["counts"]["created_week"] = export_intervals(
        #    cls.query, cls.created, "week", "YYYY-MM-DD"
        # )

        # return data

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


validate_state_transitions(Proposal.state, PROPOSAL_STATE_TRANSITIONS)


@dataclass
class ProposalInfo:
    type: ProposalType
    human_type: str
    human_type_a: str
    review_type: ReviewType
    attributes_cls: Type[Attributes]  # noqa: UP006


# Ordering here currently determines ordering in the admin UI,
# and maybe it shouldn't
PROPOSAL_INFOS: dict[ProposalType, ProposalInfo] = {
    "talk": ProposalInfo(
        type="talk",
        human_type="talk",
        human_type_a="a talk",
        review_type=ReviewType.anonymous,
        attributes_cls=ProposalTalkAttributes,
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
    ),
    "youthworkshop": ProposalInfo(
        type="youthworkshop",
        human_type="youth workshop",
        human_type_a="a youth workshop",
        review_type=ReviewType.manual,
        attributes_cls=ProposalYouthWorkshopAttributes,
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
