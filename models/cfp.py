from __future__ import annotations

from datetime import datetime, timedelta, time
import typing
from collections import namedtuple
from collections.abc import Sequence
from typing import Optional, cast
from dateutil.parser import parse as parse_date
import re
from itertools import groupby
from geoalchemy2 import Geometry, WKBElement
from geoalchemy2.shape import to_shape
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.mutable import MutableList

from sqlalchemy import Column, ForeignKey, Integer, Table, UniqueConstraint, func, select, or_
from sqlalchemy.orm import column_property, relationship, Mapped, mapped_column
from slugify.slugify import slugify
from models import (
    export_attr_counts,
    naive_utcnow,
    export_attr_edits,
    export_intervals,
    bucketise,
    event_start,
    event_end,
)

from main import db
from .user import User
from .cfp_tag import ProposalTag
from .village import Village
from . import BaseModel

if typing.TYPE_CHECKING:
    from .cfp_tag import Tag
    from .event_tickets import EventTicket
    from .volunteer.shift import Shift

__all__ = [
    "Proposal",
    "PerformanceProposal",
    "TalkProposal",
    "WorkshopProposal",
    "YouthWorkshopProposal",
    "InstallationProposal",
    "LightningTalkProposal",
    "CFPMessage",
    "CFPVote",
    "Venue",
]


HUMAN_CFP_TYPES: dict[str, str] = {
    "performance": "performance",
    "talk": "talk",
    "workshop": "workshop",
    "youthworkshop": "youth workshop",
    "installation": "installation",
    "lightning": "lightning talk",
}

# state: [allowed next state, ] pairs
CFP_STATES = {
    "edit": ["accepted", "rejected", "withdrawn", "new"],
    "new": ["accepted", "rejected", "withdrawn", "checked", "manual-review"],
    "checked": [
        "accepted",
        "rejected",
        "withdrawn",
        "anonymised",
        "anon-blocked",
        "edit",
    ],
    "rejected": ["accepted", "rejected", "withdrawn", "edit"],
    "cancelled": ["accepted", "rejected", "withdrawn", "edit"],
    "anonymised": ["accepted", "rejected", "withdrawn", "reviewed", "edit"],
    "anon-blocked": ["accepted", "rejected", "withdrawn", "reviewed", "edit"],
    "reviewed": ["accepted", "rejected", "withdrawn", "edit", "anonymised"],
    "manual-review": ["accepted", "rejected", "withdrawn", "edit"],
    "accepted": ["accepted", "rejected", "withdrawn", "finalised"],
    "finalised": ["rejected", "withdrawn", "finalised"],
    "withdrawn": ["accepted", "rejected", "withdrawn", "edit"],
}

ORDERED_STATES = [
    "edit",
    "new",
    "locked",
    "checked",
    "rejected",
    "cancelled",
    "anonymised",
    "anon-blocked",
    "manual-review",
    "reviewed",
    "accepted",
    "finalised",
    "withdrawn",
]

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

# Lengths for talks and workshops as displayed to the user
LENGTH_OPTIONS = [
    ("< 10 mins", "Shorter than 10 minutes"),
    ("10-25 mins", "10-25 minutes"),
    ("25-45 mins", "25-45 minutes"),
    ("> 45 mins", "Longer than 45 minutes"),
]

INITIAL_LIGHTNING_TALK_SLOTS = 6
LIGHTNING_TALK_SESSIONS = {
    "fri": {"human": "Friday", "slots": INITIAL_LIGHTNING_TALK_SLOTS},
    "sat": {"human": "Saturday", "slots": INITIAL_LIGHTNING_TALK_SLOTS},
    "sun": {"human": "Sunday", "slots": INITIAL_LIGHTNING_TALK_SLOTS},
}

# Options for age range displayed to the user
AGE_RANGE_OPTIONS = [
    ("All ages", "All ages"),
    (
        "Aimed at adults, but supervised kids welcome.",
        "Aimed at adults, but supervised kids welcome.",
    ),
    ("3+", "3+"),
    ("4+", "4+"),
    ("5+", "5+"),
    ("6+", "6+"),
    ("7+", "7+"),
    ("8+", "8+"),
    ("9+", "9+"),
    ("10+", "10+"),
    ("11+", "11+"),
    ("12+", "12+"),
    ("13+", "13+"),
    ("14+", "14+"),
    ("15+", "15+"),
    ("16+", "16+"),
    ("17+", "17+"),
    ("18+", "18+"),
]

# What we consider these as when scheduling
ROUGH_LENGTHS = {"> 45 mins": 50, "25-45 mins": 30, "10-25 mins": 20, "< 10 mins": 10}

# These are the time periods speakers can select as being available in the form
# This needs to go very far away
# This still needs to go very far away, it is a nightmare
PROPOSAL_TIMESLOTS = {
    "talk": (
        "fri_10_13",
        "fri_13_16",
        "fri_16_20",
        "sat_10_13",
        "sat_13_16",
        "sat_16_20",
        "sun_10_13",
        "sun_13_16",
        "sun_16_20",
    ),
    "workshop": (
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
    ),
    "youthworkshop": (
        "fri_9_13",
        "fri_13_16",
        "fri_16_20",
        "sat_9_13",
        "sat_13_16",
        "sat_16_20",
        "sun_9_13",
        "sun_13_16",
        "sun_16_20",
    ),
    "performance": (
        "fri_20_22",
        "fri_22_24",
        "sat_20_22",
        "sat_22_24",
        "sun_20_22",
        "sun_22_24",
    ),
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
SLOT_LENGTH = timedelta(minutes=10)

cfp_period = namedtuple("cfp_period", "start end")

# List of submission types which are manually reviewed rather than through
# the anonymous review system.
MANUAL_REVIEW_TYPES = ["youthworkshop", "performance", "installation"]


# This is a function rather than a constant so we can lean on the configuration
# for event start & end times rather than hard coding stuff
def get_days_map():
    event_days = [
        datetime.combine(event_start() + timedelta(days=day_idx), time.min)
        for day_idx in range((event_end() - event_start()).days + 1)
    ]
    return {ed.strftime("%a").lower(): ed for ed in event_days}


def proposal_slug(title) -> str:
    replacements = [
        ["'", ""],
    ]
    slug = slugify(title, replacements=replacements, allow_unicode=True)
    if len(slug) > 60:
        words = re.split(" +|[,.;:!?]+", title)
        break_words = ["and", "which", "with", "without", "for", "-", ""]

        for i, word in reversed(list(enumerate(words))):
            new_slug = slugify(" ".join(words[:i]), replacements=replacements, allow_unicode=True)
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


class CfpStateException(Exception):
    pass


class InvalidVenueException(Exception):
    pass


FavouriteProposal = Table(
    "favourite_proposal",
    BaseModel.metadata,
    Column("user_id", Integer, ForeignKey("user.id"), primary_key=True),
    Column(
        "proposal_id",
        Integer,
        ForeignKey("proposal.id"),
        primary_key=True,
        index=True,
    ),
)


ProposalAllowedVenues = Table(
    "proposal_allowed_venues",
    BaseModel.metadata,
    Column("proposal_id", Integer, ForeignKey("proposal.id"), primary_key=True),
    Column("venue_id", Integer, ForeignKey("venue.id"), primary_key=True),
)


class Proposal(BaseModel):
    __versioned__ = {"exclude": ["favourites", "favourite_count"]}
    __tablename__ = "proposal"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    anonymiser_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), default=None)
    created: Mapped[datetime] = mapped_column(default=naive_utcnow)
    modified: Mapped[datetime] = mapped_column(default=naive_utcnow, onupdate=naive_utcnow)
    state: Mapped[str] = mapped_column(default="new")
    type: Mapped[str] = mapped_column()  # talk, workshop or installation

    is_accepted: Mapped[bool] = column_property(state.in_(["accepted", "finalised"]))
    should_be_exported: Mapped[bool] = column_property(state.in_(["accepted", "finalised"]))

    # Core information
    title: Mapped[str] = mapped_column()
    description: Mapped[str] = mapped_column()

    equipment_required: Mapped[str | None] = mapped_column()
    funding_required: Mapped[str | None] = mapped_column()
    additional_info: Mapped[str | None] = mapped_column()
    length: Mapped[str | None] = mapped_column()  # only used for talks and workshops
    notice_required: Mapped[str | None] = mapped_column()
    private_notes: Mapped[str | None] = mapped_column()

    tags: Mapped[list[Tag]] = relationship(
        back_populates="proposals",
        cascade="all",
        secondary=ProposalTag,
    )

    # Flags
    needs_help: Mapped[bool] = mapped_column(default=False)
    needs_money: Mapped[bool] = mapped_column(default=False)
    one_day: Mapped[bool] = mapped_column(default=False)
    has_rejected_email: Mapped[bool] = mapped_column(default=False)
    user_scheduled: Mapped[bool] = mapped_column(default=False)

    # References to this table
    messages: Mapped[list[CFPMessage]] = relationship(back_populates="proposal")
    votes: Mapped[list[CFPVote]] = relationship(back_populates="proposal")
    favourites: Mapped[list[User]] = relationship(
        secondary=FavouriteProposal,
        back_populates="favourites",
    )
    user: Mapped[User] = relationship(back_populates="proposals", foreign_keys=[user_id])
    anonymiser: Mapped[User | None] = relationship(
        back_populates="anonymised_proposals", foreign_keys=[anonymiser_id]
    )
    shifts: Mapped[list["Shift"]] = relationship(back_populates="proposal")

    # Convenience for individual objects. Use an outerjoin and groupby for more than a few records
    favourite_count = column_property(
        select(func.count(FavouriteProposal.c.proposal_id))
        .where(FavouriteProposal.c.proposal_id == id)
        .scalar_subquery(),
        deferred=True,
    )

    # Fields for finalised info
    published_names: Mapped[str | None] = mapped_column()
    published_pronouns: Mapped[str | None] = mapped_column()
    published_title: Mapped[str | None] = mapped_column()
    published_description: Mapped[str | None] = mapped_column()
    arrival_period: Mapped[str | None] = mapped_column()
    departure_period: Mapped[str | None] = mapped_column()
    telephone_number: Mapped[str | None] = mapped_column()
    eventphone_number: Mapped[str | None] = mapped_column()
    may_record: Mapped[bool | None] = mapped_column()
    video_privacy: Mapped[str | None] = mapped_column()
    needs_laptop: Mapped[bool | None] = mapped_column()
    available_times: Mapped[str | None] = mapped_column()
    family_friendly: Mapped[bool | None] = mapped_column(default=False)
    content_note: Mapped[str | None] = mapped_column()

    # Fields for scheduling
    # hide_from_schedule -- do not display this item
    hide_from_schedule: Mapped[bool] = mapped_column(default=False)
    # manually_scheduled -- make the scheduler ignore this
    manually_scheduled: Mapped[bool] = mapped_column(default=False)
    allowed_venues: Mapped[list[Venue]] = relationship(
        secondary=ProposalAllowedVenues,
        back_populates="allowed_proposals",
    )
    allowed_times: Mapped[str | None] = mapped_column()
    scheduled_duration: Mapped[int | None] = mapped_column()
    scheduled_time: Mapped[datetime | None] = mapped_column()
    scheduled_venue_id: Mapped[int | None] = mapped_column(ForeignKey("venue.id"))
    potential_time: Mapped[datetime | None] = mapped_column()
    potential_venue_id: Mapped[int | None] = mapped_column(ForeignKey("venue.id"))

    scheduled_venue: Mapped[Venue | None] = relationship(
        back_populates="proposals",
        primaryjoin="Venue.id == Proposal.scheduled_venue_id",
    )
    potential_venue: Mapped[Venue | None] = relationship(
        primaryjoin="Venue.id == Proposal.potential_venue_id"
    )

    # Video stuff
    c3voc_url: Mapped[str | None] = mapped_column()
    youtube_url: Mapped[str | None] = mapped_column()
    thumbnail_url: Mapped[str | None] = mapped_column()
    video_recording_lost: Mapped[bool | None] = mapped_column(default=False)

    type_might_require_ticket = False
    tickets: Mapped[list[EventTicket]] = relationship(back_populates="proposal")

    __mapper_args__ = {"polymorphic_on": "type"}

    @classmethod
    def query_accepted(cls, include_user_scheduled=False):
        query = cls.query.filter(cls.is_accepted)
        if not include_user_scheduled:
            query = query.filter(cls.user_scheduled.is_(False))
        return query

    @classmethod
    def public_export_columns(cls):
        return [
            cls.published_title,
            cls.published_description,
            cls.published_names.label("names"),
            cls.published_pronouns.label("pronouns"),
            cls.may_record,
            cls.video_privacy,
            cls.scheduled_time,
            cls.scheduled_duration,
            Venue.name.label("venue"),
            Village.id.label("venue_village_id"),
        ]

    @classmethod
    def get_export_data(cls):
        if cls.__name__ == "Proposal":
            # Export stats for each proposal type separately
            return {}

        count_attrs = [
            "needs_help",
            "needs_money",
            "needs_laptop",
            "one_day",
            "notice_required",
            "may_record",
            "video_privacy",
            "state",
        ]

        edits_attrs = [
            "published_title",
            "published_description",
            "length",
            "equipment_required",
            "funding_required",
            "additional_info",
            "notice_required",
            "needs_help",
            "needs_money",
            "one_day",
            "has_rejected_email",
            "published_names",
            "published_pronouns",
            "arrival_period",
            "departure_period",
            "eventphone_number",
            "telephone_number",
            "may_record",
            "video_privacy",
            "needs_laptop",
            "available_times",
            "attendees",
            "cost",
            "size",
            "installation_funding",
            "age_range",
            "participant_equipment",
        ]

        # FIXME: include published_title
        proposals = cls.query.with_entities(
            cls.id,
            cls.title,
            cls.description,
            cls.favourite_count,  # don't care about performance here
            cls.length,
            cls.notice_required,
            cls.needs_money,
            cls.available_times,
            cls.allowed_times,
            cls.arrival_period,
            cls.departure_period,
            cls.needs_laptop,
            cls.may_record,
            cls.video_privacy,
        ).order_by(cls.id)

        if cls.__name__ == "WorkshopProposal":
            proposals = proposals.add_columns(cls.attendees, cls.cost, cls.age_range)
        elif cls.__name__ == "InstallationProposal":
            proposals = proposals.add_columns(cls.size, cls.installation_funding)
        elif cls.__name__ == "YouthWorkshopProposal":
            proposals = proposals.add_columns(
                cls.attendees, cls.cost, cls.age_range, cls.participant_equipment
            )

        # Some unaccepted proposals have scheduling data, but we shouldn't need to keep that
        accepted_columns = (
            User.name,
            User.email,
            cls.published_names,
            cls.published_pronouns,
            cls.scheduled_time,
            cls.scheduled_duration,
            Venue.name,
        )
        accepted_proposals = (
            proposals.filter(cls.is_accepted)
            .outerjoin(cls.scheduled_venue)
            .join(cls.user)
            .add_columns(*accepted_columns)
        )

        other_proposals = proposals.filter(~cls.is_accepted)

        user_favourites = (
            cls.query.filter(cls.is_accepted)
            .join(cls.favourites)
            .with_entities(User.id.label("user_id"), cls.id)
            .order_by(User.id)
        )

        anon_favourites = []
        for user_id, proposals in groupby(user_favourites, lambda r: r.user_id):
            anon_favourites.append([p.id for p in proposals])
        anon_favourites.sort()

        exported_public = (
            cls.query.filter(cls.should_be_exported)
            .outerjoin(cls.scheduled_venue)
            .outerjoin(Venue.village)
            .with_entities(*cls.public_export_columns())
        )

        favourite_counts = [p.favourite_count for p in proposals]

        data = {
            "private": {
                "proposals": {
                    "accepted_proposals": accepted_proposals,
                    "other_proposals": other_proposals,
                },
                "favourites": anon_favourites,
            },
            "public": {
                "proposals": {
                    "counts": export_attr_counts(cls, count_attrs),
                    "edits": export_attr_edits(cls, edits_attrs),
                    # This is still called accepted, but might not 'just' be accepted (e.g. Lightning Talks)
                    "accepted": exported_public,
                },
                "favourites": {"counts": bucketise(favourite_counts, [0, 1, 10, 20, 30, 40, 50, 100, 200])},
            },
            "tables": [
                "proposal",
                "proposal_version",
                "favourite_proposal",
                "favourite_proposal_version",
            ],
        }
        data["public"]["proposals"]["counts"]["created_week"] = export_intervals(
            cls.query, cls.created, "week", "YYYY-MM-DD"
        )

        return data

    def get_user_vote(self, user) -> CFPVote | None:
        # there can't be more than one vote per user per proposal
        return (
            db.session.execute(
                select(CFPVote).where(CFPVote.proposal_id == self.id, CFPVote.user_id == user.id)
            )
            .scalars()
            .first()
        )

    def set_state(self, state):
        state = state.lower()
        if state not in CFP_STATES:
            raise CfpStateException('"%s" is not a valid state' % state)

        if state not in CFP_STATES[self.state]:
            raise CfpStateException('"%s->%s" is not a valid transition' % (self.state, state))

        self.state = state

    def get_unread_vote_note_count(self):
        return len([v for v in self.votes if not v.has_been_read])

    def get_total_note_count(self):
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

    def has_ticket(self) -> bool:
        "Does the submitter have a ticket?"
        admission_tickets = len(list(self.user.get_owned_tickets(paid=True, type="admission_ticket")))
        return admission_tickets > 0 or self.user.will_have_ticket

    def get_allowed_venues(self) -> Sequence["Venue"]:
        if self.allowed_venues:
            return self.allowed_venues
        elif self.user_scheduled:
            return db.session.execute(select(Venue).where(~Venue.scheduled_content_only)).scalars().all()
        else:
            return (
                db.session.execute(select(Venue).where(Venue.default_for_types.any_() == self.type))
                .scalars()
                .all()
            )

    def fix_hard_time_limits(self, time_periods):
        # This should be fixed by the string periods being burned and replaced
        if self.type in HARD_START_LIMIT:
            trimmed_periods = []
            for p in time_periods:
                if (
                    p.start.hour <= HARD_START_LIMIT[self.type][0]
                    and p.start.minute < HARD_START_LIMIT[self.type][1]
                ):
                    p = cfp_period(p.start.replace(minute=HARD_START_LIMIT[self.type][1]), p.end)
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
        if not time_periods and self.available_times:
            for p in self.available_times.split(","):
                # Filter out timeslots the user selected that are not valid.
                # This can happen if a proposal is converted between types, or
                # if we remove timeslots after the proposal has been finalised
                p = p.strip()
                if p in PROPOSAL_TIMESLOTS[self.type]:
                    time_periods.append(timeslot_to_period(p, type=self.type))

        time_periods = self.fix_hard_time_limits(time_periods)
        return make_periods_contiguous(time_periods)

    def get_allowed_time_periods_serialised(self):
        return "\n".join(["%s > %s" % (v.start, v.end) for v in self.get_allowed_time_periods()])

    def get_allowed_time_periods_with_default(self):
        allowed_time_periods = self.get_allowed_time_periods()
        if not allowed_time_periods:
            allowed_time_periods = [
                timeslot_to_period(ts, type=self.type) for ts in PROPOSAL_TIMESLOTS[self.type]
            ]

        allowed_time_periods = self.fix_hard_time_limits(allowed_time_periods)
        return make_periods_contiguous(allowed_time_periods)

    def get_preferred_time_periods_with_default(self):
        preferred_time_periods = [
            timeslot_to_period(ts, type=self.type) for ts in PREFERRED_TIMESLOTS.get(self.type, [])
        ]

        preferred_time_periods = self.fix_hard_time_limits(preferred_time_periods)
        return make_periods_contiguous(preferred_time_periods)

    def overlaps_with(self, other) -> bool:
        this_start = self.potential_start_date or self.start_date
        this_end = self.potential_end_date or self.end_date
        other_start = other.potential_start_date or other.start_date
        other_end = other.potential_end_date or other.end_date

        if this_start and this_end and other_start and other_end:
            return this_end > other_start and other_end > this_start
        else:
            return False

    def get_conflicting_content(self) -> list["Proposal"]:
        # This is for attendee content, so will only conflict with other attendee
        # content or workshops. Workshops may not have a scheduled time/duration.
        if self.scheduled_time is None or self.scheduled_duration is None:
            # TODO: should this just return [] ?
            raise ValueError("scheduled_time or scheduled_duration are None")
        return [
            p
            for p in db.session.execute(
                select(Proposal).filter(
                    Proposal.id != self.id,
                    Proposal.scheduled_venue_id == self.scheduled_venue_id,
                    Proposal.scheduled_time.is_not(None),
                    Proposal.scheduled_duration.is_not(None),
                )
            )
            .scalars()
            .all()
            # These casts are safe given the query above checks for NULL
            if self.scheduled_time + timedelta(minutes=self.scheduled_duration)
            > cast(datetime, p.scheduled_time)
            and cast(datetime, p.scheduled_time) + timedelta(minutes=cast(int, p.scheduled_duration))
            > self.scheduled_time
        ]

    @property
    def is_editable(self):
        if self.state in ["new", "edit", "manual-review"]:
            return True
        return False

    @property
    def start_date(self):
        return self.scheduled_time

    @property
    def potential_start_date(self):
        return self.potential_time

    @property
    def end_date(self) -> Optional[datetime]:
        start = self.start_date
        duration = self.scheduled_duration
        if start and duration:
            return start + timedelta(minutes=int(duration))
        return None

    @property
    def potential_end_date(self) -> Optional[datetime]:
        start = self.potential_start_date
        duration = self.scheduled_duration
        if start and duration:
            return start + timedelta(minutes=int(duration))
        return None

    @property
    def slug(self):
        return proposal_slug(self.display_title)

    @property
    def latlon(self):
        return self.scheduled_venue.latlon if self.scheduled_venue else None

    @property
    def map_link(self) -> Optional[str]:
        return self.scheduled_venue.map_link if self.scheduled_venue else None

    @property
    def display_title(self) -> str:
        return self.published_title or self.title


class PerformanceProposal(Proposal):
    __mapper_args__ = {"polymorphic_identity": "performance"}
    human_type = HUMAN_CFP_TYPES["performance"]


class TalkProposal(Proposal):
    __mapper_args__ = {"polymorphic_identity": "talk"}
    human_type = HUMAN_CFP_TYPES["talk"]


class WorkshopProposal(Proposal):
    __mapper_args__ = {"polymorphic_identity": "workshop"}
    human_type = HUMAN_CFP_TYPES["workshop"]
    attendees: Mapped[str | None] = mapped_column()
    cost: Mapped[str | None] = mapped_column()
    age_range: Mapped[str | None] = mapped_column()
    participant_equipment: Mapped[str | None] = mapped_column()
    published_age_range: Mapped[str | None] = mapped_column()
    published_cost: Mapped[str | None] = mapped_column()
    published_participant_equipment: Mapped[str | None] = mapped_column()

    requires_ticket: Mapped[bool | None] = mapped_column(default=False)
    total_tickets: Mapped[int | None] = mapped_column()
    non_lottery_tickets: Mapped[int | None] = mapped_column(default=5)
    max_tickets_per_person = 2
    type_might_require_ticket = True

    def get_total_capacity(self):
        if not self.requires_ticket:
            return 0
        return self.total_tickets - self.sum_tickets_in_state("ticket")

    def has_ticket_capacity(self):
        return self.get_total_capacity() > 0

    def get_lottery_capacity(self):
        return self.get_total_capacity() - self.non_lottery_tickets

    def has_lottery_capacity(self):
        return self.get_lottery_capacity() > 0

    def sum_tickets_in_state(self, state: str) -> int:
        if not self.requires_ticket:
            return 0
        return sum([t.ticket_count for t in self.tickets if t.state == state])

    @property
    def display_cost(self) -> str:
        if self.published_cost is not None:
            cost = self.published_cost.strip()
        elif self.cost is not None:
            cost = self.cost.strip()
        else:
            return ""

        # Some people put in a string, some just put in a £ amount
        try:
            floaty = float(cost)
            # We don't want to return anything if it doesn't cost anything
            if floaty > 0:
                return "£" + cost
            else:
                return ""
        except ValueError:
            return cost

    @property
    def display_age_range(self) -> str:
        if self.published_age_range is not None:
            return self.published_age_range.strip()
        if self.age_range is not None:
            return self.age_range.strip()

        return ""

    @property
    def display_participant_equipment(self) -> str:
        if self.published_participant_equipment is not None:
            return self.published_participant_equipment.strip()
        if self.participant_equipment is not None:
            return self.participant_equipment.strip()

        return ""


class YouthWorkshopProposal(WorkshopProposal):
    __mapper_args__ = {"polymorphic_identity": "youthworkshop"}
    human_type = HUMAN_CFP_TYPES["youthworkshop"]
    valid_dbs: Mapped[bool] = mapped_column(default=False)
    max_tickets_per_person = 2


class InstallationProposal(Proposal):
    __mapper_args__ = {"polymorphic_identity": "installation"}
    human_type = HUMAN_CFP_TYPES["installation"]
    size: Mapped[str | None] = mapped_column()
    installation_funding: Mapped[str | None] = mapped_column()


class LightningTalkProposal(Proposal):
    __mapper_args__ = {"polymorphic_identity": "lightning"}
    human_type = HUMAN_CFP_TYPES["lightning"]
    slide_link: Mapped[str | None] = mapped_column()
    session: Mapped[str | None] = mapped_column(default="fri")

    should_be_exported = column_property(
        or_(
            Proposal.is_accepted.expression,
            Proposal.state == "new",
        )
    )

    @classmethod
    def public_export_columns(cls):
        return [
            # Use the submitted fields directly
            cls.title.label("published_title"),
            cls.description.label("published_description"),
            User.name.label("names"),
            # We omit fields that we don't have since they didn't go through CfP:
            # pronouns
            # may_record
            # video_privacy
            # scheduled_time
            # scheduled_duration
            # venue
            # venue_village_id
            # Lightning Talk specific fields:
            cls.session,
            cls.slide_link,
        ]

    def pretty_session(self):
        return LIGHTNING_TALK_SESSIONS[self.session]["human"]

    @classmethod
    def get_days_with_slots(cls, now=None):
        remaining_slots = cls.get_remaining_lightning_slots()
        now = datetime.now() if now is None else now

        # If we're before the event start we don't need to worry
        if now < event_start():
            return remaining_slots

        # If the day has passed (or is today) there're no more slots for it
        for day_name, date in get_days_map().items():
            if date.date() <= now.date():
                remaining_slots[day_name] = 0

        return remaining_slots

    @classmethod
    def get_remaining_lightning_slots(cls):
        # Find which day's sessions still have spaces

        slots = cls.get_total_lightning_talk_slots()

        day_counts = {
            day: count
            for (day, count) in cls.query.with_entities(
                cls.session,
                func.count(cls.id),
            )
            .filter(cls.state != "withdrawn")
            .group_by(cls.session)
            .all()
        }
        return {day: (count - day_counts.get(day, 0)) for (day, count) in slots.items()}

    @classmethod
    def get_total_lightning_talk_slots(cls):
        return {k: v["slots"] for (k, v) in LIGHTNING_TALK_SESSIONS.items()}


PYTHON_CFP_TYPES = {
    "performance": PerformanceProposal,
    "talk": TalkProposal,
    "workshop": WorkshopProposal,
    "youthworkshop": YouthWorkshopProposal,
    "installation": InstallationProposal,
}


class CFPMessage(BaseModel):
    __tablename__ = "cfp_message"
    id: Mapped[int] = mapped_column(primary_key=True)
    created: Mapped[datetime | None] = mapped_column(default=naive_utcnow)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposal.id"))

    message: Mapped[str] = mapped_column()
    # Flags
    is_to_admin: Mapped[bool | None] = mapped_column()
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


class CFPVote(BaseModel):
    __versioned__: dict = {}
    __tablename__ = "cfp_vote"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposal.id"))
    state: Mapped[str] = mapped_column()
    has_been_read: Mapped[bool] = mapped_column(default=False)

    created: Mapped[datetime] = mapped_column(default=naive_utcnow)
    modified: Mapped[datetime] = mapped_column(default=naive_utcnow, onupdate=naive_utcnow)

    vote: Mapped[int | None] = mapped_column()  # Vote can be null for abstentions
    note: Mapped[str | None] = mapped_column()

    user: Mapped[User] = relationship(back_populates="votes")
    proposal: Mapped[Proposal] = relationship(back_populates="votes")

    def __init__(self, user: User, proposal: Proposal):
        self.user = user
        self.proposal = proposal
        self.state = "new"

    def set_state(self, state):
        state = state.lower()
        if state not in VOTE_STATES:
            raise CfpStateException('"%s" is not a valid state' % state)

        if state not in VOTE_STATES[self.state]:
            raise CfpStateException('"%s->%s" is not a valid transition' % (self.state, state))

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
        data["public"]["votes"]["counts"]["created_day"] = export_intervals(
            cls.query, cls.created, "day", "YYYY-MM-DD"
        )

        return data


class Venue(BaseModel):
    __tablename__ = "venue"
    __export_data__ = False

    id: Mapped[int] = mapped_column(primary_key=True)
    village_id: Mapped[int | None] = mapped_column(ForeignKey("village.id"), default=None)
    name: Mapped[str] = mapped_column()

    # Which type of proposals are allowed to be scheduled in this venue.
    # (This is not really used yet.)
    allowed_types: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(ARRAY(db.String)),
        default=lambda: [],
    )

    # What type of proposals are the default for this venue.
    # These are where the automatic scheduler will put proposals.
    default_for_types: Mapped[list[str]] = mapped_column(
        MutableList.as_mutable(ARRAY(db.String)),
        default=lambda: [],
    )
    priority: Mapped[int | None] = mapped_column(default=0)
    capacity: Mapped[int | None] = mapped_column()
    location: Mapped[WKBElement | None] = mapped_column(Geometry("POINT", srid=4326))
    scheduled_content_only: Mapped[bool | None] = mapped_column()

    village: Mapped[Village] = relationship(
        back_populates="venues",
        primaryjoin="Village.id == Venue.village_id",
    )
    proposals: Mapped[list[Proposal]] = relationship(
        back_populates="scheduled_venue", foreign_keys=[Proposal.scheduled_venue_id]
    )
    allowed_proposals: Mapped[list[Proposal]] = relationship(
        back_populates="allowed_venues", secondary=ProposalAllowedVenues
    )

    __table_args__ = (UniqueConstraint("name", name="_venue_name_uniq"),)

    def __repr__(self):
        return "<Venue id={}, name={}>".format(self.id, self.name)

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
            for venue_names, type in db.engine.execute(
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
    def map_link(self) -> Optional[str]:
        latlon = self.latlon
        if latlon:
            return "https://map.emfcamp.org/#18.5/%s/%s/m=%s,%s" % (
                latlon[0],
                latlon[1],
                latlon[0],
                latlon[1],
            )
        return None


# TODO: change the relationships on User and Proposal to 1-to-1
db.Index("ix_cfp_vote_user_id_proposal_id", CFPVote.user_id, CFPVote.proposal_id, unique=True)

__all__ = [
    "HUMAN_CFP_TYPES",
    "PYTHON_CFP_TYPES",
    "CFP_STATES",
    "ORDERED_STATES",
    "VOTE_STATES",
    "LENGTH_OPTIONS",
    "ROUGH_LENGTHS",
    "PROPOSAL_TIMESLOTS",
    "PREFERRED_TIMESLOTS",
    "HARD_START_LIMIT",
    "REMAP_SLOT_PERIODS",
    "EVENT_SPACING",
    "cfp_period",
    "proposal_slug",
    "timeslot_to_period",
    "make_periods_contiguous",
    "CfpStateException",
    "InvalidVenueException",
    "FavouriteProposal",
    "Proposal",
    "PerformanceProposal",
    "TalkProposal",
    "WorkshopProposal",
    "YouthWorkshopProposal",
    "InstallationProposal",
    "CFPMessage",
    "CFPVote",
    "Venue",
]
