from __future__ import annotations

import dataclasses
import re
import typing
from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import (  # noqa: UP035
    Any,
    Literal,
    Self,
    Type,
    get_args,
)

import sqlalchemy
from dateutil.parser import parse as parse_date
from slugify.slugify import slugify
from sqlalchemy import (
    JSON,
    Column,
    ForeignKey,
    Integer,
    Table,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import (
    Mapped,
    column_property,
    mapped_column,
    relationship,
)

from apps.config import config
from main import db

from .. import BaseModel, naive_utcnow
from ..user import User
from . import validate_state_transitions
from .attributes import (
    Attributes,
    InstallationAttributes,
    LightningTalkAttributes,
    PerformanceAttributes,
    TalkAttributes,
    WorkshopAttributes,
    YouthWorkshopAttributes,
    attributes_proxy,
)
from .lottery import Lottery

if typing.TYPE_CHECKING:
    from ..volunteer.shift import Shift


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


# Lengths for talks and workshops as displayed to the user
DURATION_OPTIONS = [
    ("< 10 mins", "Shorter than 10 minutes"),
    ("10-25 mins", "10-25 minutes"),
    ("25-45 mins", "25-45 minutes"),
    ("> 45 mins", "Longer than 45 minutes"),
]

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
        datetime.combine(config.event_start + timedelta(days=day_idx), time.min)
        for day_idx in range((config.event_end - config.event_start).days + 1)
    ]
    return {ed.strftime("%a").lower(): ed for ed in event_days}


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


ScheduleItemType = Literal[
    "talk",
    "performance",
    "workshop",
    "youthworkshop",
    "installation",
    "lightning",
]


ScheduleItemState = Literal[
    "published",
    "unpublished",
    "hidden",
]


# scheduled implies scheduled_duration, scheduled_time, and scheduled_venue_id are all set
OccurrenceState = Literal[
    "unscheduled",
    "scheduled",
]


OCCURRENCE_STATE_TRANSITIONS: dict[OccurrenceState, set[OccurrenceState]] = {
    "unscheduled": {"scheduled"},
    "scheduled": {"unscheduled"},
}


SCHEDULE_ITEM_STATE_TRANSITIONS: dict[ScheduleItemState, set[ScheduleItemState]] = {
    "published": {"unpublished", "hidden"},
    "unpublished": {"published", "hidden"},
    "hidden": {"published", "unpublished"},
}


OccurrenceAllowedVenues: Table = Table(
    "occurrence_allowed_venues",
    BaseModel.metadata,
    Column("occurrence_id", Integer, ForeignKey("occurrence.id"), primary_key=True),
    Column("venue_id", Integer, ForeignKey("venue.id"), primary_key=True),
)


# Currently only used for talks, performances, and lightning talks
# but there's no reason that should always be the case
VideoPrivacy = Literal[
    "public",
    "review",
    "none",
]


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
from .cfp import Proposal
from .venue import Venue
