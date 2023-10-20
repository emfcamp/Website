from datetime import datetime, timedelta, time
from collections import namedtuple, defaultdict
from typing import Optional
from dateutil.parser import parse as parse_date
import re
from itertools import groupby
from geoalchemy2 import Geometry
from geoalchemy2.shape import to_shape

from sqlalchemy import UniqueConstraint, func, select
from sqlalchemy.orm import column_property
from slugify import slugify_unicode
from models import (
    export_attr_counts,
    export_attr_edits,
    export_intervals,
    bucketise,
    event_start,
    event_end,
)

from main import db
from .user import User
from .cfp_tag import ProposalTag
from . import BaseModel


HUMAN_CFP_TYPES = {
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
    "accepted": ["accepted", "rejected", "withdrawn", "finished"],
    "finished": ["rejected", "withdrawn", "finished"],
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
    "finished",
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

LIGHTNING_TALK_LENGTH = 5
INITIAL_LIGHTNING_TALK_SLOTS = 60 / LIGHTNING_TALK_LENGTH
# Try to encourage filling the Friday slot first by initially having fewer slots on Saturday & Sunday
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

PREFERRED_TIMESLOTS = {
    "workshop": (
        "fri_10_13",
        "fri_13_16",
        "fri_16_20",
        "sat_10_13",
        "sat_13_16",
        "sat_16_20",
        "sun_10_13",
        "sun_13_16",
        "sun_16_20",
    )
}

HARD_START_LIMIT = {"youthworkshop": (9, 30)}

REMAP_SLOT_PERIODS = {
    "youthworkshop": {
        "fri_16_20": ("fri", (16, 0), (20, 20)),
        "sat_16_20": ("sat", (16, 0), (20, 20)),
        "sun_16_20": ("sun", (16, 0), (19, 30)),
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
    "workshop": 2,
    "performance": 0,
    "youthworkshop": 2,
    "installation": 0,
}

cfp_period = namedtuple("cfp_period", "start end")

# We may also have other venues in the DB, but these are the ones to be
# returned by default if there are none
DEFAULT_VENUES: dict[str, list[str]] = {
    "talk": ["Stage A", "Stage B", "Stage C"],
    "workshop": ["Workshop 1", "Workshop 2", "Workshop 3", "Workshop 4", "Workshop 5"],
    "youthworkshop": ["Youth Workshop"],
    "performance": ["Stage B"],
    "installation": [],
    "lightning": ["Stage B", "Stage C"],
}

VENUE_CAPACITY = {
    "Stage A": 1000,
    "Stage B": 600,
    "Stage C": 450,
    "Workshop 1": 30,
    "Workshop 2": 30,
    "Workshop 3": 30,
    "Workshop 4": 30,
    "Workshop 5": 30,
    "Youth Workshop": 30,
}

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
    slug = slugify_unicode(title).lower()
    if len(slug) > 60:
        words = re.split(" +|[,.;:!?]+", title)
        break_words = ["and", "which", "with", "without", "for", "-", ""]

        for i, word in reversed(list(enumerate(words))):
            new_slug = slugify_unicode(" ".join(words[:i])).lower()
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
        if (
            time_period.start <= contiguous_periods[-1].end
            and contiguous_periods[-1].end < time_period.end
        ):
            contiguous_periods[-1] = cfp_period(
                contiguous_periods[-1].start, time_period.end
            )
            continue

        contiguous_periods.append(time_period)
    return contiguous_periods


def get_available_proposal_minutes():
    minutes = defaultdict(int)
    for type, slots in PROPOSAL_TIMESLOTS.items():
        periods = make_periods_contiguous(
            [timeslot_to_period(ts, type=type) for ts in slots]
        )
        for period in periods:
            minutes[type] += int(
                (period.end - period.start).total_seconds() / 60
            ) * len(DEFAULT_VENUES[type])
    return minutes


class CfpStateException(Exception):
    pass


class InvalidVenueException(Exception):
    pass


FavouriteProposal = db.Table(
    "favourite_proposal",
    BaseModel.metadata,
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column(
        "proposal_id", db.Integer, db.ForeignKey("proposal.id"), primary_key=True
    ),
)


class Proposal(BaseModel):
    __versioned__ = {"exclude": ["favourites", "favourite_count"]}
    __tablename__ = "proposal"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    anonymiser_id = db.Column(db.Integer, db.ForeignKey("user.id"), default=None)
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow
    )
    state = db.Column(db.String, nullable=False, default="new")
    type = db.Column(db.String, nullable=False)  # talk, workshop or installation

    # Core information
    title = db.Column(db.String, nullable=False)
    description = db.Column(db.String, nullable=False)
    requirements = db.Column(db.String)
    length = db.Column(db.String)  # only used for talks and workshops
    notice_required = db.Column(db.String)
    private_notes = db.Column(db.String)

    tags = db.relationship(
        "Tag",
        backref="proposals",
        cascade="all",
        secondary=ProposalTag,
    )

    # Flags
    needs_help = db.Column(db.Boolean, nullable=False, default=False)
    needs_money = db.Column(db.Boolean, nullable=False, default=False)
    one_day = db.Column(db.Boolean, nullable=False, default=False)
    has_rejected_email = db.Column(db.Boolean, nullable=False, default=False)
    user_scheduled = db.Column(db.Boolean, nullable=False, default=False)

    # References to this table
    messages = db.relationship("CFPMessage", backref="proposal")
    votes = db.relationship("CFPVote", backref="proposal")
    favourites = db.relationship(
        User, secondary=FavouriteProposal, backref=db.backref("favourites")
    )

    # Convenience for individual objects. Use an outerjoin and groupby for more than a few records
    favourite_count = column_property(
        select([func.count(FavouriteProposal.c.proposal_id)])
        .where(FavouriteProposal.c.proposal_id == id)
        .scalar_subquery(),  # type: ignore[attr-defined]
        deferred=True,
    )

    # Fields for finalised info
    published_names = db.Column(db.String)
    published_pronouns = db.Column(db.String)
    published_title = db.Column(db.String)
    published_description = db.Column(db.String)
    arrival_period = db.Column(db.String)
    departure_period = db.Column(db.String)
    telephone_number = db.Column(db.String)
    eventphone_number = db.Column(db.String)
    may_record = db.Column(db.Boolean)
    needs_laptop = db.Column(db.Boolean)
    available_times = db.Column(db.String)
    family_friendly = db.Column(db.Boolean, default=False)
    content_note = db.Column(db.String, nullable=True)

    # Fields for scheduling
    hide_from_schedule = db.Column(db.Boolean, default=False, nullable=False)
    allowed_venues = db.Column(db.String, nullable=True)
    allowed_times = db.Column(db.String, nullable=True)
    scheduled_duration = db.Column(db.Integer, nullable=True)
    scheduled_time: datetime = db.Column(db.DateTime, nullable=True)
    scheduled_venue_id = db.Column(db.Integer, db.ForeignKey("venue.id"))
    potential_time: datetime = db.Column(db.DateTime, nullable=True)
    potential_venue_id = db.Column(db.Integer, db.ForeignKey("venue.id"))

    scheduled_venue = db.relationship(
        "Venue",
        backref="proposals",
        primaryjoin="Venue.id == Proposal.scheduled_venue_id",
    )
    potential_venue = db.relationship(
        "Venue", primaryjoin="Venue.id == Proposal.potential_venue_id"
    )

    c3voc_url = db.Column(db.String)
    youtube_url = db.Column(db.String)
    thumbnail_url = db.Column(db.String)

    __mapper_args__ = {"polymorphic_on": type}

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
            "state",
        ]

        edits_attrs = [
            "published_title",
            "published_description",
            "requirements",
            "length",
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
            "needs_laptop",
            "available_times",
            "attendees",
            "cost",
            "size",
            "funds",
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
        ).order_by(cls.id)

        if cls.__name__ == "WorkshopProposal":
            proposals = proposals.add_columns(cls.attendees, cls.cost)
        elif cls.__name__ == "InstallationProposal":
            proposals = proposals.add_columns(cls.size, cls.funds)
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
            proposals.filter(cls.state.in_(["accepted", "finished"]))
            .outerjoin(cls.scheduled_venue)
            .join(cls.user)
            .add_columns(*accepted_columns)
        )

        other_proposals = proposals.filter(~cls.state.in_(["accepted", "finished"]))

        user_favourites = (
            cls.query.filter(cls.state.in_(["accepted", "finished"]))
            .join(cls.favourites)
            .with_entities(User.id.label("user_id"), cls.id)
            .order_by(User.id)
        )

        anon_favourites = []
        for user_id, proposals in groupby(user_favourites, lambda r: r.user_id):
            anon_favourites.append([p.id for p in proposals])
        anon_favourites.sort()

        public_columns = (
            cls.published_title,
            cls.published_description,
            cls.published_names.label("names"),
            cls.published_pronouns.label("pronouns"),
            cls.may_record,
            cls.scheduled_time,
            cls.scheduled_duration,
            Venue.name.label("venue"),
        )
        accepted_public = (
            cls.query.filter(cls.state.in_(["accepted", "finished"]))
            .outerjoin(cls.scheduled_venue)
            .with_entities(*public_columns)
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
                    "accepted": accepted_public,
                },
                "favourites": {
                    "counts": bucketise(
                        favourite_counts, [0, 1, 10, 20, 30, 40, 50, 100, 200]
                    )
                },
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

    def get_user_vote(self, user) -> "CFPVote":
        # there can't be more than one vote per user per proposal
        return CFPVote.query.filter_by(proposal_id=self.id, user_id=user.id).first()

    def set_state(self, state):
        state = state.lower()
        if state not in CFP_STATES:
            raise CfpStateException('"%s" is not a valid state' % state)

        if state not in CFP_STATES[self.state]:
            raise CfpStateException(
                '"%s->%s" is not a valid transition' % (self.state, state)
            )

        self.state = state

    def get_unread_vote_note_count(self):
        return len([v for v in self.votes if not v.has_been_read])

    def get_total_note_count(self):
        return len([v for v in self.votes if v.note and len(v.note) > 0])

    def get_unread_messages(self, user):
        return [
            m
            for m in self.messages
            if (not m.has_been_read and m.is_user_recipient(user))
        ]

    def get_unread_count(self, user):
        return len(self.get_unread_messages(user))

    def mark_messages_read(self, user):
        messages = self.get_unread_messages(user)
        for msg in messages:
            msg.has_been_read = True
        return len(messages)

    def has_ticket(self) -> bool:
        "Does the submitter have a ticket?"
        admission_tickets = len(
            list(self.user.get_owned_tickets(paid=True, type="admission_ticket"))
        )
        return admission_tickets > 0 or self.user.will_have_ticket

    def get_allowed_venues(self) -> list["Venue"]:
        # FIXME: this should reference a foreign key instead
        if self.user_scheduled:
            venue_names = [self.scheduled_venue.name]
        elif self.allowed_venues:
            venue_names = [v.strip() for v in self.allowed_venues.split(",")]
        else:
            venue_names = DEFAULT_VENUES[self.type]

        if not venue_names:
            return []

        found = Venue.query.filter(Venue.name.in_(venue_names)).all()
        # If we didn't actually find all the venues we're using, bail hard
        if len(found) != len(venue_names):
            raise InvalidVenueException("Invalid Venue in allowed_venues!")

        return found

    def get_allowed_venues_serialised(self):
        return ",".join([v.name for v in self.get_allowed_venues()])

    def fix_hard_time_limits(self, time_periods):
        # This should be fixed by the string periods being burned and replaced
        if self.type in HARD_START_LIMIT:
            trimmed_periods = []
            for p in time_periods:
                if (
                    p.start.hour <= HARD_START_LIMIT[self.type][0]
                    and p.start.minute < HARD_START_LIMIT[self.type][1]
                ):
                    p = cfp_period(
                        p.start.replace(minute=HARD_START_LIMIT[self.type][1]), p.end
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
                        time_periods.append(
                            cfp_period(
                                parse_date(start.strip()), parse_date(end.strip())
                            )
                        )
                    # If someone has entered garbage, dump the lot
                    except ValueError as e:
                        time_periods = []
                        break

        # If we've not overridden it, use the user-specified periods
        if not time_periods and self.available_times:
            for p in self.available_times.split(","):
                if p:
                    time_periods.append(timeslot_to_period(p.strip(), type=self.type))

        time_periods = self.fix_hard_time_limits(time_periods)
        return make_periods_contiguous(time_periods)

    def get_allowed_time_periods_serialised(self):
        return "\n".join(
            ["%s > %s" % (v.start, v.end) for v in self.get_allowed_time_periods()]
        )

    def get_allowed_time_periods_with_default(self):
        allowed_time_periods = self.get_allowed_time_periods()
        if not allowed_time_periods:
            allowed_time_periods = [
                timeslot_to_period(ts, type=self.type)
                for ts in PROPOSAL_TIMESLOTS[self.type]
            ]

        allowed_time_periods = self.fix_hard_time_limits(allowed_time_periods)
        return make_periods_contiguous(allowed_time_periods)

    def get_preferred_time_periods_with_default(self):
        preferred_time_periods = [
            timeslot_to_period(ts, type=self.type)
            for ts in PREFERRED_TIMESLOTS.get(self.type, [])
        ]

        preferred_time_periods = self.fix_hard_time_limits(preferred_time_periods)
        return make_periods_contiguous(preferred_time_periods)

    def overlaps_with(self, other) -> bool:
        if self.potential_start_date:
            return (
                self.potential_end_date > other.potential_start_date
                and other.potential_end_date > self.potential_start_date
            )
        else:
            return self.end_date > other.start_date and other.end_date > self.start_date

    def get_conflicting_content(self) -> list["Proposal"]:
        # I gave up trying to do this as SQL via SQLAlchemy's filter expressions.
        return [
            p
            for p in Proposal.query.filter(
                Proposal.id != self.id,
                Proposal.scheduled_venue_id == self.scheduled_venue_id,
                Proposal.scheduled_time >= self.start_date,
            ).all()
            if p.overlaps_with(self)
        ]

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
        start = self.start_date
        duration = self.scheduled_duration
        if start and duration:
            return start + timedelta(minutes=int(duration))
        return None

    @property
    def slug(self):
        return proposal_slug(self.display_title)

    @property
    def latlon(self):
        if self.scheduled_venue and self.scheduled_venue.location:
            loc = to_shape(self.scheduled_venue.location)
            return (loc.y, loc.x)
        return None

    @property
    def map_link(self) -> Optional[str]:
        latlon = self.latlon
        if latlon:
            return "https://map.emfcamp.org/#18.5/%s/%s" % (latlon[0], latlon[1])
        return None

    @property
    def display_title(self) -> str:
        return self.published_title or self.title

    @property
    def display_cost(self) -> str:
        if self.cost is None and self.published_cost is None:
            return ""

        if self.published_cost is not None:
            cost = self.published_cost.strip()
        else:
            cost = self.cost.strip()

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


class PerformanceProposal(Proposal):
    __mapper_args__ = {"polymorphic_identity": "performance"}
    human_type = HUMAN_CFP_TYPES["performance"]


class TalkProposal(Proposal):
    __mapper_args__ = {"polymorphic_identity": "talk"}
    human_type = HUMAN_CFP_TYPES["talk"]


class WorkshopProposal(Proposal):
    __mapper_args__ = {"polymorphic_identity": "workshop"}
    human_type = HUMAN_CFP_TYPES["workshop"]
    attendees = db.Column(db.String)
    cost = db.Column(db.String)
    age_range = db.Column(db.String)
    participant_equipment = db.Column(db.String)
    published_age_range = db.Column(db.String)
    published_cost = db.Column(db.String)
    published_participant_equipment = db.Column(db.String)


class YouthWorkshopProposal(WorkshopProposal):
    __mapper_args__ = {"polymorphic_identity": "youthworkshop"}
    human_type = HUMAN_CFP_TYPES["youthworkshop"]
    valid_dbs = db.Column(db.Boolean, nullable=False, default=False)


class InstallationProposal(Proposal):
    __mapper_args__ = {"polymorphic_identity": "installation"}
    human_type = HUMAN_CFP_TYPES["installation"]
    size = db.Column(db.String)
    funds = db.Column(db.String, nullable=True)


class LightningTalkProposal(Proposal):
    __mapper_args__ = {"polymorphic_identity": "lightning"}
    human_type = HUMAN_CFP_TYPES["lightning"]
    slide_link = db.Column(db.String, nullable=True)
    session = db.Column(db.String, default="fri")

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
    id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    from_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    proposal_id = db.Column(db.Integer, db.ForeignKey("proposal.id"), nullable=False)

    message = db.Column(db.String, nullable=False)
    # Flags
    is_to_admin = db.Column(db.Boolean)
    has_been_read = db.Column(db.Boolean, default=False)

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
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    proposal_id = db.Column(db.Integer, db.ForeignKey("proposal.id"), nullable=False)
    state = db.Column(db.String, nullable=False)
    has_been_read = db.Column(db.Boolean, nullable=False, default=False)

    created = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    modified = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    vote = db.Column(db.Integer)  # Vote can be null for abstentions
    note = db.Column(db.String)

    def __init__(self, user: User, proposal: Proposal):
        self.user = user
        self.proposal = proposal
        self.state = "new"

    def set_state(self, state):
        state = state.lower()
        if state not in VOTE_STATES:
            raise CfpStateException('"%s" is not a valid state' % state)

        if state not in VOTE_STATES[self.state]:
            raise CfpStateException(
                '"%s->%s" is not a valid transition' % (self.state, state)
            )

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

    id = db.Column(db.Integer, primary_key=True)
    village_id = db.Column(
        db.Integer, db.ForeignKey("village.id"), nullable=True, default=None
    )
    name = db.Column(db.String, nullable=False)
    type = db.Column(db.String, nullable=True)
    priority = db.Column(db.Integer, nullable=True, default=0)
    location = db.Column(Geometry("POINT", srid=4326))
    scheduled_content_only = db.Column(db.Boolean)
    village = db.relationship(
        "Village",
        backref="venues",
        primaryjoin="Village.id == Venue.village_id",
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

    @classmethod
    def get_by_name(cls, name):
        return cls.query.filter_by(name=name).one()


# TODO: change the relationships on User and Proposal to 1-to-1
db.Index(
    "ix_cfp_vote_user_id_proposal_id", CFPVote.user_id, CFPVote.proposal_id, unique=True
)

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
    "DEFAULT_VENUES",
    "VENUE_CAPACITY",
    "proposal_slug",
    "timeslot_to_period",
    "make_periods_contiguous",
    "get_available_proposal_minutes",
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
