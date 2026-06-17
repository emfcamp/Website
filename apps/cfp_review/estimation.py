from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import pendulum
from pendulum import Duration
from sqlalchemy.sql import not_

from main import db
from models.content import (
    ScheduleItem,
    ScheduleItemType,
    Venue,
)
from models.content.schedule import SCHEDULE_ITEM_INFOS, ScheduleItemInfo
from models.content.venue import TimeBlock

# Estimates either cover automatically-scheduled or manually-scheduled content.
type EstimateType = Literal["automatic", "manual"]


@dataclass
class CFPEstimate:
    type: EstimateType
    schedule_item_info: ScheduleItemInfo
    occurrence_count: int
    missing_occurrences: int
    available_time: timedelta
    allocated_time: timedelta
    remaining_time: timedelta
    unknown_durations: int
    venues: list[Venue]


def get_available_proposal_time(type: ScheduleItemType, estimate_type: EstimateType) -> Duration:
    blocks_query = db.session.query(TimeBlock).where(TimeBlock.type == type)
    match estimate_type:
        case "manual":
            blocks_query = blocks_query.where(not_(TimeBlock.automatic))
        case "automatic":
            blocks_query = blocks_query.where(TimeBlock.automatic)

    return sum(
        ((pendulum.instance(block.end) - pendulum.instance(block.start)) for block in blocks_query.all()),
        Duration(),
    )


def get_cfp_estimate(schedule_item_type: ScheduleItemType, estimate_type: EstimateType) -> CFPEstimate:
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

    missing_occurrences = 0
    occurrence_count = 0

    for schedule_item in schedule_items:
        if len(schedule_item.occurrences) == 0:
            missing_occurrences += 1

        for occurrence in schedule_item.occurrences:
            if occurrence.cancelled:
                continue

            # If an occurrence is allowed to be placed in *any* automatic timeblock,
            # we count it as automatically scheduled.
            #
            # Items in manually-scheduled venues should have their allowed_venues set correctly.
            can_be_automatically_scheduled = any(
                time_block.automatic for time_block in occurrence.time_blocks()
            )

            if (can_be_automatically_scheduled and estimate_type == "manual") or (
                (not can_be_automatically_scheduled) and estimate_type == "automatic"
            ):
                continue

            occurrence_count += 1

            if not occurrence.scheduled_duration:
                unknown_durations += 1
                continue

            duration = Duration(minutes=occurrence.scheduled_duration)
            allocated_time += duration + occurrence.changeover_time

    available_venues_query = (
        db.session.query(Venue).join(Venue.time_blocks).filter(TimeBlock.type == schedule_item_type)
    )
    match estimate_type:
        case "automatic":
            available_venues_query = available_venues_query.filter(TimeBlock.automatic)
        case "manual":
            available_venues_query = available_venues_query.filter(not_(TimeBlock.automatic))

    available_venues = available_venues_query.group_by(Venue.id).all()

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

    available_time = get_available_proposal_time(schedule_item_type, estimate_type)

    return CFPEstimate(
        type=estimate_type,
        schedule_item_info=SCHEDULE_ITEM_INFOS[schedule_item_type],
        occurrence_count=occurrence_count,
        missing_occurrences=missing_occurrences,
        available_time=available_time,
        allocated_time=allocated_time,
        remaining_time=available_time - allocated_time,
        unknown_durations=unknown_durations,
        venues=available_venues,
    )
