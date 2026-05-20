from dataclasses import dataclass
from datetime import timedelta

import pendulum
from pendulum import Duration
from sqlalchemy import select

from main import db
from models.content import (
    ScheduleItem,
    ScheduleItemType,
    Venue,
)
from models.content.venue import TimeBlock


@dataclass
class CFPEstimate:
    schedule_item_type: ScheduleItemType
    schedule_item_count: int
    available_time: timedelta
    allocated_time: timedelta
    remaining_time: timedelta
    unknown_durations: int
    venues: list[Venue]


def get_available_proposal_time(type: ScheduleItemType) -> Duration:
    blocks = db.session.query(TimeBlock).where(TimeBlock.type == type).all()
    return sum(
        ((pendulum.instance(block.end) - pendulum.instance(block.start)) for block in blocks),
        Duration(),
    )


def get_cfp_estimate(schedule_item_type: ScheduleItemType) -> CFPEstimate:
    """Calculate estimated scheduling capacity statistics for a given proposal type."""
    schedule_items = (
        db.session.query(ScheduleItem)
        .filter(
            ScheduleItem.type == schedule_item_type,
            ScheduleItem.official_content,
            ScheduleItem.type != "cancelled",
        )
        .all()
    )

    allocated_time = Duration()
    unknown_durations: int = 0

    for schedule_item in schedule_items:
        for occurrence in schedule_item.occurrences:
            if occurrence.cancelled:
                continue

            if not occurrence.scheduled_duration:
                unknown_durations += 1
                continue

            duration = Duration(minutes=occurrence.scheduled_duration)
            allocated_time += duration + occurrence.changeover_time

    available_venues = list(
        db.session.scalars(
            select(Venue)
            .join(Venue.time_blocks)
            .filter(TimeBlock.type == schedule_item_type)
            .group_by(Venue.id)
        )
    )

    # Correct for changeover period not being needed at the end of the day
    # This can go negative if there aren't many proposals accepted yet, so clamp to 0
    #
    # FIXME: We now don't know if changeover time is needed at the end of a TimeBlock.
    # But this is also a pretty small adjustment given that this is a rough calculation.
    # If we're this close to the wire, we should be running the scheduler to get a better indication.
    # - Russ
    #
    # num_days = len(get_days_map().items())
    # changeover_correction = changeover_time * num_days * len(available_venues)
    # allocated_time = max(allocated_time - changeover_correction, Duration())

    available_time = get_available_proposal_time(schedule_item_type)

    return CFPEstimate(
        schedule_item_type=schedule_item_type,
        schedule_item_count=len(schedule_items),
        available_time=available_time,
        allocated_time=allocated_time,
        remaining_time=available_time - allocated_time,
        unknown_durations=unknown_durations,
        venues=available_venues,
    )
