from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select

from main import db
from models.content import (
    EVENT_SPACING,
    PROPOSAL_TIMESLOTS,
    ROUGH_DURATIONS,
    SLOT_DURATION,
    ScheduleItem,
    ScheduleItemType,
    Venue,
    get_days_map,
    make_periods_contiguous,
    timeslot_to_period,
)


@dataclass
class CFPEstimate:
    schedule_item_type: ScheduleItemType
    schedule_item_count: int
    available_time: timedelta
    allocated_time: timedelta
    remaining_time: timedelta
    unknown_durations: int
    venues: list[Venue]


def get_available_proposal_minutes():
    minutes = defaultdict(int)
    venue_names_by_type = Venue.emf_venue_names_by_type()
    for type, slots in PROPOSAL_TIMESLOTS.items():
        if type not in venue_names_by_type:
            continue
        periods = make_periods_contiguous([timeslot_to_period(ts, type=type) for ts in slots])
        for period in periods:
            minutes[type] += int((period.end - period.start).total_seconds() / 60) * len(
                venue_names_by_type[type]
            )
    return minutes


def get_cfp_estimate(schedule_item_type: ScheduleItemType) -> CFPEstimate:
    """Calculate estimated scheduling capacity statistics for a given proposal type."""
    changeover_time = SLOT_DURATION * EVENT_SPACING[schedule_item_type]

    schedule_items = (
        db.session.query(ScheduleItem)
        .filter(ScheduleItem.state == "published", ScheduleItem.type == schedule_item_type)
        .all()
    )

    allocated_time = timedelta()
    unknown_durations: int = 0

    for schedule_item in schedule_items:
        for occurrence in schedule_item.occurrences:
            duration = None
            if occurrence.scheduled_duration:
                duration = timedelta(minutes=occurrence.scheduled_duration)
            elif schedule_item.proposal and schedule_item.proposal.duration in ROUGH_DURATIONS:
                duration = timedelta(minutes=ROUGH_DURATIONS[schedule_item.proposal.duration])
            else:
                unknown_durations += 1
                continue

            allocated_time += duration + changeover_time

    num_days = len(get_days_map().items())

    available_venues = list(
        db.session.execute(select(Venue).where(Venue.default_for_types.any_() == schedule_item_type))
        .scalars()
        .all()
    )

    # Correct for changeover period not being needed at the end of the day
    # This can go negative if there aren't many proposals accepted yet, so clamp to 0
    changeover_correction = changeover_time * num_days * len(available_venues)
    allocated_time = max(allocated_time - changeover_correction, timedelta(0))

    available_minutes = get_available_proposal_minutes()
    available_time = timedelta(minutes=available_minutes[schedule_item_type])

    return CFPEstimate(
        schedule_item_type=schedule_item_type,
        schedule_item_count=len(schedule_items),
        available_time=available_time,
        allocated_time=allocated_time,
        remaining_time=available_time - allocated_time,
        unknown_durations=unknown_durations,
        venues=available_venues,
    )
