import dataclasses
import re
import typing
from collections import defaultdict, namedtuple
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import (  # noqa: UP035
    Any,
    Literal,
    Self,
    Type,
    get_args,
)

import sqlalchemy
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
    validates,
)

from apps.config import config
from main import db

from .. import BaseModel, naive_utcnow
from ..user import User
from . import validate_state_transitions
from .attributes import (
    Attributes,
    FamilyWorkshopAttributes,
    FilmAttributes,
    LightningTalkAttributes,
    PerformanceAttributes,
    TalkAttributes,
    WorkshopAttributes,
    attributes_proxy,
)
from .lottery import Lottery

if typing.TYPE_CHECKING:
    from ..volunteer.shift import Shift


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

# Number of slots (in 10min increments) that must be between proposals of this
# type in the same venue
EVENT_SPACING = {
    "talk": 1,
    "workshop": 3,
    "performance": 0,
    "familyworkshop": 2,
    "installation": 0,
    "film": 2,
}

# The size of a scheduling slot
SLOT_DURATION = timedelta(minutes=10)

cfp_period = namedtuple("cfp_period", "start end")


# This is a function rather than a constant so we can lean on the configuration
# for event start & end times rather than hard coding stuff
def get_days_map():
    return {ed.strftime("%a").lower(): ed for ed in config.event_days}


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
    "film",
    "familyworkshop",
    "installation",
    "lightning",
]


ScheduleItemState = Literal[
    "published",
    "unpublished",
    "cancelled",
]

SCHEDULE_ITEM_STATE_TRANSITIONS: dict[ScheduleItemState, set[ScheduleItemState]] = {
    "published": {"unpublished", "cancelled"},
    "unpublished": {"published", "cancelled"},
    "cancelled": {"published", "unpublished"},
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


class ScheduleItemAvailability(BaseModel):
    """A time range when a speaker is available to present a ScheduleItem.

    Several of these may be associated with a ScheduleItem.
    """

    id: Mapped[int] = mapped_column(primary_key=True)

    schedule_item_id: Mapped[int] = mapped_column(ForeignKey("schedule_item.id"))
    schedule_item: Mapped[ScheduleItem] = relationship(back_populates="availability")

    start: Mapped[datetime]
    end: Mapped[datetime]


class ScheduleItem(BaseModel):
    """An item of content in the schedule.

    This contains the details displayed in the schedule on the website. ScheduleItems
    are created for a Proposal if it's submitted through the CfP and accepted, but
    they can also be created directly by villages.
    """

    __versioned__: dict[str, Any] = {"exclude": ["favourited_by", "favourite_count"]}

    id: Mapped[int] = mapped_column(primary_key=True)

    #: The type of the ScheduleItem, which controls how it's displayed in the schedule
    type: Mapped[ScheduleItemType]

    #: The state of the ScheduleItem
    state: Mapped[ScheduleItemState] = mapped_column(
        sqlalchemy.Enum(
            *get_args(ScheduleItemState),
            native_enum=False,
        ),
        default="published",
    )

    #: The user who owns the ScheduleItem.
    #: An attendee ScheduleItem has an associated owner who can edit it
    #: (in addition to anyone who's an admin for the scheduled village)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))

    #: The proposal for this ScheduleItem. May be None in the case of attendee content.
    proposal_id: Mapped[int | None] = mapped_column(ForeignKey("proposal.id"))

    # Most of these are optional so that people can fill out data over time
    # A schedule item should ideally be unpublished until then
    names: Mapped[str | None]
    pronouns: Mapped[str | None]
    title: Mapped[str]
    description: Mapped[str | None]
    short_description: Mapped[str | None]

    #: Whether this is official content or attendee content.
    official_content: Mapped[bool] = mapped_column(default=False)

    #: Whether this should be recorded
    video_privacy: Mapped[VideoPrivacy] = mapped_column(default="public")

    #: The speaker's availability to present this item - applies to all occurrences.
    availability: Mapped[list[ScheduleItemAvailability]] = relationship(back_populates="schedule_item")

    contact_telephone: Mapped[str | None]

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

    has_availability = column_property(
        select(func.count(ScheduleItemAvailability.id) > 0)
        .where(ScheduleItemAvailability.schedule_item_id == id)
        .scalar_subquery(),
        deferred=True,
    )

    def cancel(self) -> None:
        """Mark this ScheduleItem as cancelled, as well as any occurrences."""
        self.state = "cancelled"
        for occurrence in self.occurrences:
            occurrence.cancel()

    @property
    def presenters(self) -> set[User]:
        """The list of Users who are presenting this ScheduleItem, which may be different to the
            user who owns it.

        Currently only returns a single user, or an empty list for manually-added ScheduleItems.
        This is used by the automatic scheduler to prevent speaker clashes.
        """
        # Manually-added ScheduleItems will have the team member who created them as self.user.
        # We don't want this to be displayed or used by the scheduler to detect clashes.
        if self.proposal:
            return {self.user}
        return set()

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
    attributes_cls: Type[Attributes]  # noqa: UP006
    supports_lottery: bool = False
    default_max_tickets_per_entry: int | None = None


SCHEDULE_ITEM_INFOS: dict[ScheduleItemType, ScheduleItemInfo] = {
    # ScheduleItems that typically come via the review process
    "talk": ScheduleItemInfo(
        type="talk",
        human_type="talk",
        human_type_a="a talk",
        attributes_cls=TalkAttributes,
    ),
    "performance": ScheduleItemInfo(
        type="performance",
        human_type="performance",
        human_type_a="a performance",
        attributes_cls=PerformanceAttributes,
    ),
    "workshop": ScheduleItemInfo(
        type="workshop",
        human_type="workshop",
        human_type_a="a workshop",
        supports_lottery=True,
        attributes_cls=WorkshopAttributes,
        default_max_tickets_per_entry=2,
    ),
    "film": ScheduleItemInfo(
        type="film",
        human_type="film",
        human_type_a="a film",
        attributes_cls=FilmAttributes,
    ),
    "familyworkshop": ScheduleItemInfo(
        type="familyworkshop",
        human_type="family workshop",
        human_type_a="a family workshop",
        supports_lottery=True,
        attributes_cls=FamilyWorkshopAttributes,
        default_max_tickets_per_entry=5,
    ),
    # ScheduleItem types that are only created directly
    "lightning": ScheduleItemInfo(
        type="lightning",
        human_type="lightning talk",
        human_type_a="a lightning talk",
        attributes_cls=LightningTalkAttributes,
    ),
}


class Occurrence(BaseModel):
    """
    An occurrence of a ScheduleItem. This indicates when and where a ScheduleItem will occur.

    In future there may be multiple occurrences of a ScheduleItem, for example if the same workshop is presented twice,
    however this is not currently guaranteed to work.
    """

    __versioned__: dict[str, Any] = {}
    __table_args__ = (UniqueConstraint("schedule_item_id", "occurrence_num"),)

    id: Mapped[int] = mapped_column(primary_key=True)

    cancelled: Mapped[bool] = mapped_column(default=False)

    schedule_item_id: Mapped[int] = mapped_column(ForeignKey("schedule_item.id"))
    occurrence_num: Mapped[int]
    lottery_id: Mapped[int | None] = mapped_column(ForeignKey("lottery.id"))

    #: Prevents the automatic scheduler from trying to move this occurrence
    manually_scheduled: Mapped[bool] = mapped_column(default=False)

    scheduled_duration: Mapped[int | None] = mapped_column()  # in minutes

    #: The time this occurrence is scheduled to happen at.
    #: This may be changed by the automatic scheduler, unless `manually_scheduled` is set.
    scheduled_time: Mapped[datetime | None] = mapped_column()
    scheduled_venue_id: Mapped[int | None] = mapped_column(ForeignKey("venue.id"))

    #: Potential timeslots for this occurrence in a proposed schedule.
    potential_scheduled_slots: Mapped[list[PotentialScheduleOccurrence]] = relationship(
        back_populates="occurrence"
    )

    c3voc_url: Mapped[str | None]
    youtube_url: Mapped[str | None]
    thumbnail_url: Mapped[str | None]
    video_recording_lost: Mapped[bool] = mapped_column(default=False)

    schedule_item: Mapped[ScheduleItem] = relationship(
        "ScheduleItem", back_populates="occurrences", foreign_keys=[schedule_item_id]
    )

    #: Venues this occurrence is allowed to be scheduled in.
    #: If the `manually_scheduled` flag is set, and `scheduled_venue` is set, this is ignored.
    #: `get_allowed_venues()` should be used to access this, which will default if this isn't set.
    allowed_venues: Mapped[list[Venue]] = relationship(
        secondary=OccurrenceAllowedVenues,
        back_populates="allowed_occurrences",
    )

    #: The venue this occurrence is scheduled in. This may be changed by the automatic scheduler,
    #: unless `manually_scheduled` is set.
    scheduled_venue: Mapped[Venue | None] = relationship(
        back_populates="occurrences",
        primaryjoin="Venue.id == Occurrence.scheduled_venue_id",
    )
    shifts: Mapped[list[Shift]] = relationship(back_populates="occurrence")
    lottery: Mapped[Lottery | None] = relationship(back_populates="occurrence")

    proposal: AssociationProxy[Proposal | None] = association_proxy("schedule_item", "proposal")
    user: AssociationProxy[User] = association_proxy("schedule_item", "user")

    @validates("scheduled_duration")
    def validate_scheduled_duration(self, key: str, value: int | None) -> int | None:
        """SQLAlchemy validator to ensure duration is a multiple of the slot duration."""
        if value is None:
            return value

        # When creating an occurrence, the schedule_item isn't available so we can't run this check here
        # Attendee content does not need to conform to the slot duration.
        if not self.schedule_item or not self.schedule_item.official_content:
            return value

        duration_minutes = SLOT_DURATION.total_seconds() / 60

        if value % duration_minutes != 0:
            raise ValueError(
                f"Scheduled duration ({value} minutes) is not a multiple of slot duration ({duration_minutes} minutes)"
            )
        return value

    def is_valid_slot(self, start_time: datetime, venue: Venue, user: User | None = None) -> bool:
        """Check whether this occurrence can be scheduled in a given start_time and venue.

        For village content, a user object should be passed in.
        """
        if not self.schedule_item.official_content:
            if venue.allows_attendee_content:
                return True
            if venue.village and user is not None and user in venue.village.admins():
                return True
            return False

        if self.scheduled_duration is None:
            raise ValueError("Unable to set slot for Occurrence with no duration")

        for time_block in venue.time_blocks:
            if (
                start_time >= time_block.start
                and start_time + timedelta(minutes=self.scheduled_duration) <= time_block.end
                and self.schedule_item.type == time_block.type
            ):
                return True

        return False

    def set_slot(self, start_time: datetime, venue: Venue, user: User | None = None) -> None:
        """Set the start_time and venue, validating that this is allowed.

        For village content, a user object should be passed in.
        """
        if not self.is_valid_slot(start_time, venue, user):
            raise ValueError("Invalid slot")
        self.scheduled_time = start_time
        self.scheduled_venue = venue

    def cancel(self) -> None:
        """Cancel this occurrence."""
        self.cancelled = True

    @property
    def video_privacy(self) -> VideoPrivacy:
        # Occurrences can inherit their video privacy from the ScheduleItem.
        # It's unlikely we'll have multiple occurrences of anything which is recorded anyway.
        return self.schedule_item.video_privacy

    @property
    def availability(self) -> list[ScheduleItemAvailability]:
        """The speaker's availability to present this occurrence.

        Inherited from the ScheduleItem.
        """
        return self.schedule_item.availability

    def get_allowed_venues(self) -> set[Venue]:
        """Get the allowed venues for this Occurrence, defaulting to venues with automatic TimeBlocks if none are set."""
        if self.allowed_venues:
            return set(self.allowed_venues)

        return set(
            db.session.scalars(
                select(Venue)
                .join(Venue.time_blocks)
                .where(TimeBlock.type == self.schedule_item.type, TimeBlock.automatic)
                .group_by(Venue.id)
            )
        )

    @property
    def valid_allowed_venues(self) -> set[Venue]:
        """A list of venues this Occurrence could be scheduled in. This is used to offer the correct
        selection of venues to admin users when setting allowed_venues.
        """
        if self.schedule_item.official_content:
            return set(
                db.session.scalars(
                    select(Venue).join(Venue.time_blocks).where(TimeBlock.type == self.schedule_item.type)
                )
            )
        return set(db.session.scalars(select(Venue).where(Venue.allows_attendee_content == True)))

    def time_blocks(self) -> Iterable[TimeBlock]:
        """TimeBlocks which this Occurrence can be scheduled in.

        This takes into account whether the Occurrence has been manually scheduled, but it doesn't
        take into account speaker availability.
        """
        if self.manually_scheduled and self.scheduled_venue and self.scheduled_time:
            # Occurrence is manually scheduled, so we only return the TimeBlock which it's scheduled in
            for timeblock in self.scheduled_venue.time_blocks:
                if timeblock.type == self.schedule_item.type and (
                    timeblock.start <= self.scheduled_time < timeblock.end
                ):
                    yield timeblock
                    break

        else:
            for venue in self.get_allowed_venues():
                for timeblock in venue.time_blocks:
                    if timeblock.type == self.schedule_item.type:
                        yield timeblock

    def allowed_times(self, automatic: bool) -> dict[Venue, list[tuple[datetime, datetime]]]:
        """Return a mapping of Venue -> time range for when this occurrence is allowed to be scheduled,
            which is the input into the automatic scheduler.

        This is the intersection of speaker availability and the allowed TimeBlocks for this content type.
        """
        assert self.schedule_item.official_content

        if self.manually_scheduled and self.scheduled_venue and self.scheduled_time:
            # Manually scheduled - return a single time range which encompasses the scheduled time.
            assert self.scheduled_end_time
            return {self.scheduled_venue: [(self.scheduled_time, self.scheduled_end_time)]}

        result: dict[Venue, list[tuple[datetime, datetime]]] = defaultdict(list)
        for time_block in self.time_blocks():
            if time_block.automatic != automatic:
                continue

            if not self.availability:
                # No availability provided, return all available timeblocks
                result[time_block.venue].append((time_block.start, time_block.end))
                continue

            for availability in self.availability:
                if availability.start <= time_block.end and availability.end >= time_block.start:
                    result[time_block.venue].append(
                        (max(availability.start, time_block.start), min(availability.end, time_block.end))
                    )
        return result

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
        if not self.scheduled:
            return []

        assert self.scheduled_time is not None
        assert self.scheduled_duration is not None

        venue_occurrences: list[Occurrence] = list(
            db.session.scalars(
                select(Occurrence).filter(
                    Occurrence.id != self.id,
                    Occurrence.scheduled_venue_id == self.scheduled_venue_id,
                )
            )
        )

        conflicts = []
        for other in venue_occurrences:
            if not other.scheduled:
                continue
            assert other.scheduled_time is not None
            assert other.scheduled_duration is not None

            self_finish = self.scheduled_time + timedelta(minutes=self.scheduled_duration)
            other_finish = other.scheduled_time + timedelta(minutes=other.scheduled_duration)
            if self_finish > other.scheduled_time and other_finish > self.scheduled_time:
                conflicts.append(other)

        return conflicts

    @property
    def changeover_time(self) -> timedelta:
        return SLOT_DURATION * EVENT_SPACING[self.schedule_item.type]

    @property
    def potential_slot(self) -> PotentialScheduleOccurrence | None:
        if len(self.potential_scheduled_slots) > 0:
            return sorted(list(self.potential_scheduled_slots), reverse=True)[0]
        return None

    @property
    def scheduled_end_time(self) -> datetime | None:
        start = self.scheduled_time
        duration = self.scheduled_duration
        if start and duration:
            return start + timedelta(minutes=duration)
        return None

    @property
    def potential_time(self) -> datetime | None:
        if slot := self.potential_slot:
            return slot.start_time
        return None

    @property
    def potential_end_time(self) -> datetime | None:
        if slot := self.potential_slot:
            duration = self.scheduled_duration
            if duration:
                return slot.start_time + timedelta(minutes=duration)
        return None

    @property
    def potential_venue(self) -> Venue | None:
        if slot := self.potential_slot:
            return slot.venue
        return None

    @property
    def scheduled(self) -> bool:
        """Whether this occurrence has been scheduled"""
        return (
            not self.cancelled
            and self.scheduled_time is not None
            and self.scheduled_venue is not None
            and self.scheduled_duration is not None
        )


from .cfp import Proposal
from .potential_schedule import PotentialScheduleOccurrence
from .venue import TimeBlock, Venue
