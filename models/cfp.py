from __future__ import annotations

import dataclasses
import re
import typing
from collections import namedtuple
from dataclasses import MISSING, dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import (  # noqa: UP035
    Any,
    Literal,
    Self,
    Type,
    TypeVar,
    get_args,
)

import sqlalchemy
from dateutil.parser import parse as parse_date
from geoalchemy2 import Geometry, WKBElement
from geoalchemy2.shape import to_shape
from slugify.slugify import slugify
from sqlalchemy import (
    JSON,
    Column,
    ForeignKey,
    Integer,
    Table,
    UniqueConstraint,
    event,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import (
    LoaderCallableStatus,
    Mapped,
    column_property,
    mapped_column,
    relationship,
)

from main import db
from models import (
    event_end,
    event_start,
    export_attr_counts,
    export_attr_edits,
    export_intervals,
    naive_utcnow,
)

from . import BaseModel
from .cfp_tag import ProposalTag, Tag
from .lottery import Lottery
from .user import User
from .village import Village

if typing.TYPE_CHECKING:
    from .volunteer.shift import Shift

__all__ = [
    "Attributes",
    "Occurrence",
    "Proposal",
    "ProposalMessage",
    "ProposalType",
    "ProposalVote",
    "ScheduleItem",
    "ScheduleItemType",
    "Venue",
]


class StateTransitionException(Exception):
    pass


TState = TypeVar("TState")


# TODO: this should become a column wrapper type
def validate_state_transitions(column: Any, allowed_transitions: dict[TState, set[TState]]) -> None:
    def on_state_set(target, value, oldvalue, initiator):
        if oldvalue == LoaderCallableStatus.NO_VALUE:
            return
        if value == oldvalue:
            return
        if value not in allowed_transitions[oldvalue]:
            raise StateTransitionException(f"{target} cannot transition from {oldvalue} to {value}")

    event.listen(column, "set", on_state_set)


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
    "anonymised": {"accepted", "rejected", "withdrawn", "reviewed", "edit", "conduct-blocked"},
    "anon-blocked": {"accepted", "rejected", "withdrawn", "reviewed", "edit", "conduct-blocked"},
    "manual-review": {"accepted", "rejected", "withdrawn", "edit", "conduct-blocked"},
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


# Lengths for talks and workshops as displayed to the user
DURATION_OPTIONS = [
    ("< 10 mins", "Shorter than 10 minutes"),
    ("10-25 mins", "10-25 minutes"),
    ("25-45 mins", "25-45 minutes"),
    ("> 45 mins", "Longer than 45 minutes"),
]


ScheduleItemState = Literal[
    "published",
    "unpublished",
    "hidden",
]

SCHEDULE_ITEM_STATE_TRANSITIONS: dict[ScheduleItemState, set[ScheduleItemState]] = {
    "published": {"unpublished", "hidden"},
    "unpublished": {"published", "hidden"},
    "hidden": {"published", "unpublished"},
}


# scheduled implies scheduled_duration, scheduled_time, and scheduled_venue_id are all set
OccurrenceState = Literal[
    "unscheduled",
    "scheduled",
]


OCCURRENCE_STATE_TRANSITIONS: dict[OccurrenceState, set[OccurrenceState]] = {
    "unscheduled": {"scheduled"},
    "scheduled": {"unscheduled"},
}


# Options for age range displayed to the user
AGE_RANGE_OPTIONS = [
    ("all", "Suitable for all ages"),
    ("u5", "Under 5"),
    ("u12", "Under 12"),
    ("12+", "Age 12+"),
    ("14+", "Age 14+"),
    ("16+", "Age 16+"),
    ("18+", "Age 18+"),
    ("other", "Other"),
]

# What we consider these as when scheduling
ROUGH_DURATIONS = {"> 45 mins": 50, "25-45 mins": 30, "10-25 mins": 20, "< 10 mins": 10}

# These are the time periods speakers can select as being available in the form
# This needs to go very far away
# This still needs to go very far away, it is a nightmare
PROPOSAL_TIMESLOTS = {
    "talk": [
        "fri_10_13",
        "fri_13_16",
        "fri_16_20",
        "sat_10_13",
        "sat_13_16",
        "sat_16_20",
        "sun_10_13",
        "sun_13_16",
        "sun_16_20",
    ],
    "workshop": [
        "fri_10_13",
        "fri_13_16",
        "fri_16_20",
        "fri_20_22",
        "fri_22_24",
        "sat_10_13",
        "sat_13_16",
        "sat_16_20",
        "sat_20_22",
        "sat_22_24",
        "sun_10_13",
        "sun_13_16",
        "sun_16_20",
    ],
    "youthworkshop": [
        "fri_9_13",
        "fri_13_16",
        "fri_16_20",
        "sat_9_13",
        "sat_13_16",
        "sat_16_20",
        "sun_9_13",
        "sun_13_16",
        "sun_16_20",
    ],
    "performance": [
        "fri_20_22",
        "fri_22_24",
        "sat_20_22",
        "sat_22_24",
        "sun_20_22",
        "sun_22_24",
    ],
}

# Causes the scheduler to prefer putting these things in these time ranges,
# used to pack things into attendee-friendly hours even though speakers are
# happy to give workshops at midnight. These do not need to overlap with other
# slot definitions.
PREFERRED_TIMESLOTS = {
    "workshop": (
        "fri_12_18",
        "sat_12_18",
        "sun_12_18",
    )
}

HARD_START_LIMIT = {"youthworkshop": (9, 30)}

# Because I have excavated this from my memory: This is a horrendous quick hack
# to allow us to override the timeslot periods that are valid for a proposal
# type as speakers select them from the list and we don't store actual time
# values. BUT WE SHOULD.
REMAP_SLOT_PERIODS = {
    "talk": {
        "fri_10_13": ("fri", (11, 0), (13, 00)),  # Talks start at 11 on Friday
        "sun_16_20": ("sun", (16, 0), (18, 40)),  # Talks end at 6 on Sunday
    },
    "youthworkshop": {
        "fri_16_20": ("fri", (16, 0), (20, 20)),
        "sat_16_20": ("sat", (16, 0), (20, 20)),
        "sun_16_20": ("sun", (16, 0), (19, 20)),
    },
    "performance": {
        "fri_22_24": ("fri", (22, 0), (25, 30)),
        "sat_22_24": ("sat", (22, 0), (25, 30)),
        "sun_22_24": ("sun", (22, 0), (25, 30)),
    },
}

# Number of slots (in 10min increments) that must be between proposals of this
# type in the same venue
EVENT_SPACING = {
    "talk": 1,
    "workshop": 3,
    "performance": 0,
    "youthworkshop": 2,
    "installation": 0,
}

# The size of a scheduling slot
SLOT_DURATION = timedelta(minutes=10)

cfp_period = namedtuple("cfp_period", "start end")


# This is a function rather than a constant so we can lean on the configuration
# for event start & end times rather than hard coding stuff
def get_days_map():
    event_days = [
        datetime.combine(event_start() + timedelta(days=day_idx), time.min)
        for day_idx in range((event_end() - event_start()).days + 1)
    ]
    return {ed.strftime("%a").lower(): ed for ed in event_days}


def schedule_item_slug(title: str, allow_unicode: bool = True) -> str:
    replacements = [
        ["'", ""],
    ]
    slug: str = slugify(title, replacements=replacements, allow_unicode=allow_unicode)
    if len(slug) > 60:
        words = re.split(" +|[,.;:!?]+", title)
        break_words = ["and", "which", "with", "without", "for", "-", ""]

        for i, word in reversed(list(enumerate(words))):
            new_slug = slugify(" ".join(words[:i]), replacements=replacements, allow_unicode=allow_unicode)
            if word in break_words:
                if len(new_slug) > 10 and not len(new_slug) > 60:
                    slug = new_slug
                    break

            elif len(slug) > 60 and len(new_slug) > 10:
                slug = new_slug

    if len(slug) > 60:
        slug = slug[:60] + "-"

    return slug


def timeslot_to_period(slot_string, type=None):
    start = end = None
    days_map = get_days_map()

    if type in REMAP_SLOT_PERIODS and slot_string in REMAP_SLOT_PERIODS[type]:
        day, start_time, end_time = REMAP_SLOT_PERIODS[type][slot_string]
        start = days_map[day] + timedelta(hours=start_time[0], minutes=start_time[1])
        end = days_map[day] + timedelta(hours=end_time[0], minutes=end_time[1])

    else:
        day, start_h, end_h = slot_string.split("_")
        start = days_map[day] + timedelta(hours=int(start_h))
        end = days_map[day] + timedelta(hours=int(end_h))

    return cfp_period(start, end)


# Reduces the time periods to the smallest contiguous set we can
def make_periods_contiguous(time_periods):
    if not time_periods:
        return []

    time_periods.sort(key=lambda x: x.start)
    contiguous_periods = [time_periods.pop(0)]
    for time_period in time_periods:
        if time_period.start <= contiguous_periods[-1].end and contiguous_periods[-1].end < time_period.end:
            contiguous_periods[-1] = cfp_period(contiguous_periods[-1].start, time_period.end)
            continue

        contiguous_periods.append(time_period)
    return contiguous_periods


class InvalidVenueException(Exception):
    pass


FavouriteScheduleItem = Table(
    "favourite_schedule_item",
    BaseModel.metadata,
    Column("user_id", Integer, ForeignKey("user.id"), primary_key=True),
    Column(
        "schedule_item_id",
        Integer,
        ForeignKey("schedule_item.id"),
        primary_key=True,
        index=True,
    ),
)


OccurrenceAllowedVenues = Table(
    "occurrence_allowed_venues",
    BaseModel.metadata,
    Column("occurrence_id", Integer, ForeignKey("occurrence.id"), primary_key=True),
    Column("venue_id", Integer, ForeignKey("venue.id"), primary_key=True),
)


"""
Skeleton classes to provide typing for attributes.

These are mostly shared between Proposals and ScheduleItems,
and will be copied when the proposal is about to be finalised.
There are some extra Proposal attributes that will not be copied.

Anything entered by users probably wants to be a string or enum,
as people write things like "20-25" or "20 (space permitting)".

We allow None for strings to simplify copying from forms,
and converting to/from JSON. We include defaults to make
adding/removing fields easier, but don't account for removed fields yet.

It's possible to filter the underlying attributes_json column with
sqlalchemy, and part of why we don't use TypedDict is to avoid confusion
with that column.
"""


@dataclass
class Attributes:
    pass


# Attributes used by both Proposal and ScheduleItem


@dataclass
class TalkAttributes(Attributes):
    content_note: str | None = None
    needs_laptop: bool = False
    family_friendly: bool = False


@dataclass
class PerformanceAttributes(Attributes):
    pass


@dataclass
class WorkshopAttributes(Attributes):
    age_range: str | None = None
    participant_cost: str | None = None
    participant_equipment: str | None = None
    content_note: str | None = None
    family_friendly: bool = False


@dataclass
class YouthWorkshopAttributes(Attributes):
    age_range: str | None = None
    participant_cost: str | None = None
    participant_equipment: str | None = None
    content_note: str | None = None
    # No need for family_friendly


@dataclass
class InstallationAttributes(Attributes):
    size: str | None = None


@dataclass
class LightningTalkAttributes(Attributes):
    slide_link: str | None = None
    session: str | None = None


# Attributes only used by the review process
# These won't get copied across when creating a schedule item


@dataclass
class ProposalTalkAttributes(TalkAttributes):
    pass


@dataclass
class ProposalPerformanceAttributes(PerformanceAttributes):
    pass


@dataclass
class ProposalWorkshopAttributes(WorkshopAttributes):
    participant_count: str | None = None


@dataclass
class ProposalYouthWorkshopAttributes(YouthWorkshopAttributes):
    participant_count: str | None = None
    valid_dbs: bool | None = None


@dataclass
class ProposalInstallationAttributes(InstallationAttributes):
    grant_requested: str | None = None


# LightningTalks don't go through the review process


def attributes_proxy(attributes_cls: type[Attributes], store: dict[str, Any]) -> type[Attributes]:
    class AttributesProxy(attributes_cls):  # type: ignore[valid-type, misc]
        """Forwards dataclass fields to a backing dict, blocking access to anything not defined by the dataclass."""

        def __new__(cls, *args, **kwargs):
            obj = super().__new__(cls)
            object.__setattr__(obj, "_store", store)
            return obj

        def __getattribute__(self, name: str) -> Any:
            if name.startswith("__") or name == "_store":
                return super().__getattribute__(name)
            if name not in self.__dataclass_fields__:
                raise AttributeError(name)
            return self._store.get(name)

        def __setattr__(self, name: str, value: Any) -> None:
            if name not in self.__dataclass_fields__:
                raise AttributeError(name)
            if self._store.get(name, MISSING) != value:
                self._store[name] = value
            else:
                # MutableDict counts this as a mutation
                pass

        def __repr__(self) -> str:
            return f"<{self.__class__.__name__} {self._store!r}>"

    AttributesProxy.__name__ = f"{attributes_cls.__name__}Proxy"
    return AttributesProxy


def convert_attributes_between_types(old_attributes: Attributes, new_attributes: Attributes) -> None:
    # Logic to transfer attributes. Any not copied will be lost except in history.
    # There aren't currently many attributes that can safely be copied across.
    attributes_to_copy = [
        "family_friendly",
    ]
    if isinstance(old_attributes, WorkshopAttributes | YouthWorkshopAttributes) and isinstance(
        new_attributes, WorkshopAttributes | YouthWorkshopAttributes
    ):
        attributes_to_copy += [
            "participant_count",
            "age_range",
            "participant_cost",
            "participant_equipment",
        ]
        # family_friendly and valid_dbs can't be copied

    for a in attributes_to_copy:
        if hasattr(old_attributes, a):
            setattr(new_attributes, a, getattr(old_attributes, a))


def copy_common_attributes(old_attributes: Attributes, new_attributes: Attributes) -> None:
    for n in new_attributes.__dataclass_fields__:
        setattr(new_attributes, n, getattr(old_attributes, n))


class ReviewType(StrEnum):
    anonymous = "anonymous"
    manual = "manual"
    none = "none"


# Currently only used for talks, performances, and lightning talks
# but there's no reason that should always be the case
VideoPrivacy = Literal[
    "public",
    "review",
    "none",
]

ProposalType = Literal[
    "talk",
    "performance",
    "workshop",
    "youthworkshop",
    "installation",
]


ScheduleItemType = Literal[
    "talk",
    "performance",
    "workshop",
    "youthworkshop",
    "installation",
    "lightning",
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


class ScheduleItem(BaseModel):
    """An item of content in the schedule.

    This contains the details displayed in the schedule on the website. ScheduleItems
    are created for a Proposal if it's submitted through the CfP and accepted, but
    they can also be created directly by villages.
    """

    __versioned__: dict[str, Any] = {"exclude": ["favourited_by", "favourite_count"]}

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[ScheduleItemType]
    state: Mapped[ScheduleItemState] = mapped_column(
        sqlalchemy.Enum(
            *get_args(ScheduleItemState),
            native_enum=False,
        ),
        default="published",
    )

    # An attendee schedule item has an associated owner who can edit it
    # (in addition to anyone who's an admin for the scheduled village)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposal.id"))

    # Most of these are optional so that people can fill out data over time
    # A schedule item should ideally be unpublished until then
    names: Mapped[str | None]
    pronouns: Mapped[str | None]
    title: Mapped[str]
    description: Mapped[str | None]
    short_description: Mapped[str | None]

    official_content: Mapped[bool] = mapped_column(default=False)

    # Copied to new Occurrences, will usually be confirmed in finalisation
    default_video_privacy: Mapped[VideoPrivacy]

    arrival_period: Mapped[str | None]
    departure_period: Mapped[str | None]
    available_times: Mapped[str | None]

    contact_telephone: Mapped[str | None]
    contact_eventphone: Mapped[str | None]

    # Used for sorting in the CfP review page
    modified: Mapped[datetime] = mapped_column(default=naive_utcnow, onupdate=naive_utcnow)

    attributes_json: Mapped[dict[str, Any] | None] = mapped_column(
        "attributes", MutableDict.as_mutable(JSON), nullable=False, default=dict
    )

    user: Mapped[User] = relationship(back_populates="schedule_items", foreign_keys=[user_id])
    proposal: Mapped[Proposal | None] = relationship(
        back_populates="schedule_item", foreign_keys=[proposal_id]
    )
    occurrences: Mapped[list[Occurrence]] = relationship(
        back_populates="schedule_item", order_by="Occurrence.occurrence_num"
    )

    is_published: Mapped[bool] = column_property(state.in_({"published"}))

    favourited_by: Mapped[list[User]] = relationship(
        secondary=FavouriteScheduleItem,
        back_populates="favourites",
    )

    favourite_count = column_property(
        select(func.count(FavouriteScheduleItem.c.schedule_item_id))
        .where(FavouriteScheduleItem.c.schedule_item_id == id)
        .scalar_subquery(),
        deferred=True,
    )

    @property
    def slug(self):
        return schedule_item_slug(self.title)

    @property
    def type_info(self) -> ScheduleItemInfo:
        return SCHEDULE_ITEM_INFOS[self.type]

    @property
    def human_type(self) -> str:
        return self.type_info.human_type

    @property
    def human_type_a(self) -> str:
        # Same as human_type but includes a/an
        return self.type_info.human_type_a

    @property
    def has_lottery(self) -> bool:
        return any(occurrence.lottery for occurrence in self.occurrences)

    @property
    def attributes(self) -> Attributes:
        if self.attributes_json is None:
            self.attributes_json = {}
        Proxy = attributes_proxy(self.type_info.attributes_cls, self.attributes_json)
        return Proxy(**self.attributes_json)

    @attributes.setter
    def attributes(self, value: Attributes) -> None:
        self.attributes_json = dataclasses.asdict(value)


validate_state_transitions(ScheduleItem.state, SCHEDULE_ITEM_STATE_TRANSITIONS)


@dataclass
class ScheduleItemInfo:
    type: ScheduleItemType
    human_type: str
    human_type_a: str
    supports_lottery: bool
    needs_occurrence: bool
    attributes_cls: Type[Attributes]  # noqa: UP006
    default_max_tickets_per_entry: int | None = None


SCHEDULE_ITEM_INFOS: dict[ScheduleItemType, ScheduleItemInfo] = {
    # ScheduleItems that typically come via the review process
    "talk": ScheduleItemInfo(
        type="talk",
        human_type="talk",
        human_type_a="a talk",
        supports_lottery=False,
        needs_occurrence=True,
        attributes_cls=TalkAttributes,
    ),
    "performance": ScheduleItemInfo(
        type="performance",
        human_type="performance",
        human_type_a="a performance",
        supports_lottery=False,
        needs_occurrence=True,
        attributes_cls=PerformanceAttributes,
    ),
    "workshop": ScheduleItemInfo(
        type="workshop",
        human_type="workshop",
        human_type_a="a workshop",
        supports_lottery=True,
        needs_occurrence=True,
        attributes_cls=WorkshopAttributes,
        default_max_tickets_per_entry=2,
    ),
    "youthworkshop": ScheduleItemInfo(
        type="youthworkshop",
        human_type="youth workshop",
        human_type_a="a youth workshop",
        supports_lottery=True,
        needs_occurrence=True,
        attributes_cls=YouthWorkshopAttributes,
        default_max_tickets_per_entry=5,
    ),
    "installation": ScheduleItemInfo(
        type="installation",
        human_type="installation",
        human_type_a="an installation",
        supports_lottery=False,
        needs_occurrence=False,
        attributes_cls=InstallationAttributes,
    ),
    # ScheduleItem types that are only created directly
    "lightning": ScheduleItemInfo(
        type="lightning",
        human_type="lightning talk",
        human_type_a="a lightning talk",
        supports_lottery=False,
        needs_occurrence=True,
        attributes_cls=LightningTalkAttributes,
    ),
}


class Occurrence(BaseModel):
    """
    An occurrence of a ScheduleItem. This indicates when and where a ScheduleItem will occur.

    In some cases (such as workshops), there might be multiple occurrences of a ScheduleItem.
    """

    __versioned__: dict[str, Any] = {}
    __table_args__ = (UniqueConstraint("schedule_item_id", "occurrence_num"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    state: Mapped[OccurrenceState] = mapped_column(
        sqlalchemy.Enum(
            *get_args(OccurrenceState),
            native_enum=False,
        ),
        default="unscheduled",
    )

    schedule_item_id: Mapped[int] = mapped_column(ForeignKey("schedule_item.id"))
    occurrence_num: Mapped[int]
    lottery_id: Mapped[int | None] = mapped_column(ForeignKey("lottery.id"))

    # Prevents the scheduler from trying to move this occurrence
    manually_scheduled: Mapped[bool] = mapped_column(default=False)

    scheduled_duration: Mapped[int | None]  # in minutes
    allowed_times: Mapped[str | None]
    # allowed_venues has an association table
    potential_time: Mapped[datetime | None]
    potential_venue_id: Mapped[int | None] = mapped_column(ForeignKey("venue.id"))
    scheduled_time: Mapped[datetime | None]
    scheduled_venue_id: Mapped[int | None] = mapped_column(ForeignKey("venue.id"))

    video_privacy: Mapped[VideoPrivacy]

    c3voc_url: Mapped[str | None]
    youtube_url: Mapped[str | None]
    thumbnail_url: Mapped[str | None]
    video_recording_lost: Mapped[bool] = mapped_column(default=False)

    schedule_item: Mapped[ScheduleItem] = relationship(
        "ScheduleItem", back_populates="occurrences", foreign_keys=[schedule_item_id]
    )
    allowed_venues: Mapped[list[Venue]] = relationship(
        secondary=OccurrenceAllowedVenues,
        back_populates="allowed_occurrences",
    )
    potential_venue: Mapped[Venue | None] = relationship(
        primaryjoin="Venue.id == Occurrence.potential_venue_id"
    )
    scheduled_venue: Mapped[Venue | None] = relationship(
        back_populates="occurrences",
        primaryjoin="Venue.id == Occurrence.scheduled_venue_id",
    )
    shifts: Mapped[list[Shift]] = relationship(back_populates="occurrence")
    lottery: Mapped[Lottery | None] = relationship(back_populates="occurrence")

    proposal: AssociationProxy[Proposal | None] = association_proxy("schedule_item", "proposal")
    user: AssociationProxy[User] = association_proxy("schedule_item", "user")

    @property
    def valid_allowed_venues(self) -> list[Venue]:
        if self.schedule_item.official_content:
            return list(
                db.session.scalars(select(Venue).where(Venue.allowed_types.any_() == self.schedule_item.type))
            )
        return list(db.session.scalars(select(Venue).where(Venue.allows_attendee_content == True)))

    def fix_hard_time_limits(self, time_periods):
        # This should be fixed by the string periods being burned and replaced
        if self.schedule_item.type in HARD_START_LIMIT:
            trimmed_periods = []
            for p in time_periods:
                if (
                    p.start.hour <= HARD_START_LIMIT[self.schedule_item.type][0]
                    and p.start.minute < HARD_START_LIMIT[self.schedule_item.type][1]
                ):
                    p = cfp_period(
                        p.start.replace(minute=HARD_START_LIMIT[self.schedule_item.type][1]), p.end
                    )
                trimmed_periods.append(p)
            time_periods = trimmed_periods
        return time_periods

    def get_allowed_time_periods(self):
        time_periods = []

        if self.allowed_times:
            for p in self.allowed_times.split("\n"):
                if p:
                    start, end = p.split(" > ")
                    try:
                        time_periods.append(cfp_period(parse_date(start.strip()), parse_date(end.strip())))
                    # If someone has entered garbage, dump the lot
                    except ValueError:
                        time_periods = []
                        break

        # If we've not overridden it, use the user-specified periods
        if not time_periods and self.schedule_item.available_times:
            for p in self.schedule_item.available_times.split(","):
                # Filter out timeslots the user selected that are not valid.
                # This can happen if a proposal is converted between types, or
                # if we remove timeslots after the proposal has been finalised.
                p = p.strip()
                if p in PROPOSAL_TIMESLOTS[self.schedule_item.type]:
                    time_periods.append(timeslot_to_period(p, type=self.schedule_item.type))

        time_periods = self.fix_hard_time_limits(time_periods)
        return make_periods_contiguous(time_periods)

    def get_allowed_time_periods_serialised(self):
        return "\n".join([f"{v.start} > {v.end}" for v in self.get_allowed_time_periods()])

    def get_allowed_time_periods_with_default(self):
        allowed_time_periods = self.get_allowed_time_periods()
        if not allowed_time_periods:
            allowed_time_periods = [
                timeslot_to_period(ts, type=self.schedule_item.type)
                for ts in PROPOSAL_TIMESLOTS[self.schedule_item.type]
            ]

        allowed_time_periods = self.fix_hard_time_limits(allowed_time_periods)
        return make_periods_contiguous(allowed_time_periods)

    def get_preferred_time_periods_with_default(self):
        preferred_time_periods = [
            timeslot_to_period(ts, type=self.schedule_item.type)
            for ts in PREFERRED_TIMESLOTS.get(self.schedule_item.type, [])
        ]

        preferred_time_periods = self.fix_hard_time_limits(preferred_time_periods)
        return make_periods_contiguous(preferred_time_periods)

    def overlaps_with(self, other: Self) -> bool:
        this_start = self.potential_time or self.scheduled_time
        other_start = other.potential_time or other.scheduled_time
        this_end = self.potential_end_time or self.scheduled_end_time
        other_end = other.potential_end_time or other.scheduled_end_time

        if this_start and this_end and other_start and other_end:
            return this_end > other_start and other_end > this_start
        return False

    def get_conflicting_content(self) -> list[Occurrence]:
        # We don't care about schedule item state because we don't want to
        # make it hard to yank something temporarily.

        # This is for attendee content, so will only conflict with other attendee
        # content or workshops. Workshops may not have a scheduled time/duration.
        # TODO: what does the last bit above mean? Workshops have a scheduled time.
        if self.state != "scheduled":
            return []

        venue_occurrences: list[Occurrence] = list(
            db.session.scalars(
                select(Occurrence).filter(
                    Occurrence.id != self.id,
                    Occurrence.state == "scheduled",
                    Occurrence.scheduled_venue_id == self.scheduled_venue_id,
                )
            )
        )

        conflicts = []
        for other in venue_occurrences:
            # Safe assertions given the check for state == "scheduled":
            assert self.scheduled_time is not None
            assert self.scheduled_duration is not None
            assert other.scheduled_time is not None
            assert other.scheduled_duration is not None

            self_finish = self.scheduled_time + timedelta(minutes=self.scheduled_duration)
            other_finish = other.scheduled_time + timedelta(minutes=other.scheduled_duration)
            if self_finish > other.scheduled_time and other_finish > self.scheduled_time:
                conflicts.append(other)

        return conflicts

    # Basically only available if state == "scheduled"
    @property
    def scheduled_end_time(self) -> datetime | None:
        start = self.scheduled_time
        duration = self.scheduled_duration
        if start and duration:
            return start + timedelta(minutes=duration)
        return None

    # Can be accessible before state == "scheduled"
    @property
    def potential_end_time(self) -> datetime | None:
        start = self.potential_time
        duration = self.scheduled_duration
        if start and duration:
            return start + timedelta(minutes=duration)
        return None


validate_state_transitions(Occurrence.state, OCCURRENCE_STATE_TRANSITIONS)


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

    def is_user_recipient(self, user):
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
            cls.query.join(User)
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
            cls.query, cls.created, "day", "YYYY-MM-DD"
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


class Venue(BaseModel):
    """
    A location where content can be scheduled.

    This can be an official talk stage, a village location, or any other
    place on site.
    """

    __tablename__ = "venue"
    __export_data__ = False
    __table_args__ = (UniqueConstraint("name", name="_venue_name_uniq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    village_id: Mapped[int | None] = mapped_column(ForeignKey("village.id"), default=None)
    name: Mapped[str]

    # Which type of schedule item are allowed to be scheduled in this venue.
    allowed_types: Mapped[list[ScheduleItemType]] = mapped_column(
        MutableList.as_mutable(ARRAY(db.String)),
        default=list,
    )

    # What type of schedule items are the default for this venue.
    # These are where the automatic scheduler will put items.
    default_for_types: Mapped[list[ScheduleItemType]] = mapped_column(
        MutableList.as_mutable(ARRAY(db.String)),
        default=list,
    )
    priority: Mapped[int] = mapped_column(default=0)
    capacity: Mapped[int | None]
    location: Mapped[WKBElement | None] = mapped_column(Geometry("POINT", srid=4326))
    allows_attendee_content: Mapped[bool | None]

    village: Mapped[Village] = relationship(
        back_populates="venues",
        primaryjoin="Village.id == Venue.village_id",
    )
    occurrences: Mapped[list[Occurrence]] = relationship(
        back_populates="scheduled_venue", foreign_keys=[Occurrence.scheduled_venue_id]
    )
    allowed_occurrences: Mapped[list[Occurrence]] = relationship(
        back_populates="allowed_venues",
        secondary=OccurrenceAllowedVenues,
    )

    def __repr__(self):
        return f"<Venue id={self.id}, name={self.name}>"

    @property
    def __geo_interface__(self):
        """GeoJSON-like representation of the object for the map."""
        if not self.location:
            return None

        location = to_shape(self.location)

        return {
            "type": "Feature",
            "properties": {
                "id": self.id,
                "name": self.name,
                "type": self.type,
            },
            "geometry": location.__geo_interface__,
        }

    @property
    def is_emf_venue(self):
        return bool(self.default_for_types)

    @classmethod
    def emf_venues(cls):
        return cls.query.filter(db.func.array_length(cls.default_for_types, 1) > 0).all()

    @classmethod
    def emf_venue_names_by_type(cls):
        """Return a map of proposal type to official EMF venues."""
        unnest = db.func.unnest(cls.default_for_types).table_valued()
        return {
            type: venue_names
            for venue_names, type in db.session.execute(
                db.select(db.func.array_agg(cls.name), unnest.column)
                .join(unnest, db.true())
                .group_by(unnest.column)
            )
        }

    @classmethod
    def get_by_name(cls, name):
        return cls.query.filter_by(name=name).one()

    @property
    def latlon(self):
        if self.location:
            loc = to_shape(self.location)
            return (loc.y, loc.x)
        if self.village and self.village.latlon:
            return self.village.latlon
        return None

    @property
    def map_link(self) -> str | None:
        if not self.latlon:
            return None
        lat, lon = self.latlon
        return f"https://map.emfcamp.org/#18.5/{lat}/{lon}/m={lat},{lon}"


__all__ = [
    "DURATION_OPTIONS",
    "EVENT_SPACING",
    "HARD_START_LIMIT",
    "PREFERRED_TIMESLOTS",
    "PROPOSAL_INFOS",
    "PROPOSAL_TIMESLOTS",
    "REMAP_SLOT_PERIODS",
    "ROUGH_DURATIONS",
    "VOTE_STATES",
    "Attributes",
    "FavouriteScheduleItem",
    "InstallationAttributes",
    "InvalidVenueException",
    "PerformanceAttributes",
    "Proposal",
    "ProposalMessage",
    "ProposalVote",
    "TalkAttributes",
    "Venue",
    "WorkshopAttributes",
    "YouthWorkshopAttributes",
    "cfp_period",
    "make_periods_contiguous",
    "schedule_item_slug",
    "timeslot_to_period",
]
