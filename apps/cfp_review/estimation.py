from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

import pendulum
from pendulum import Duration
from sqlalchemy.sql import and_, not_

from main import db
from models.content import (
    ScheduleItem,
    ScheduleItemType,
    Venue,
)
from models.content.schedule import EVENT_SPACING, SCHEDULE_ITEM_INFOS, SLOT_DURATION, ScheduleItemInfo
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


def get_blocks_for_type(type: ScheduleItemType, estimate_type: EstimateType) -> list[TimeBlock]:
    blocks_query = db.session.query(TimeBlock).where(TimeBlock.type == type)
    match estimate_type:
        case "manual":
            blocks_query = blocks_query.where(not_(and_(TimeBlock.automatic, TimeBlock.default)))
        case "automatic":
            blocks_query = blocks_query.where(and_(TimeBlock.automatic, TimeBlock.default))

    return blocks_query.all()


def get_available_proposal_time(type: ScheduleItemType, estimate_type: EstimateType) -> Duration:
    blocks = get_blocks_for_type(type, estimate_type)
    return sum(
        ((pendulum.instance(block.end) - pendulum.instance(block.start)) for block in blocks),
        Duration(),
    )


def get_cfp_estimate(schedule_item_type: ScheduleItemType, estimate_type: EstimateType) -> CFPEstimate:
    """Calculate estimated scheduling capacity statistics for a given proposal type."""
    schedule_items = (
        db.session.query(ScheduleItem)
        .filter(
            ScheduleItem.type == schedule_item_type,
            ScheduleItem.official_content,
            ScheduleItem.state != "cancelled",
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

            # An occurrence counts as automatically scheduled if it can be placed in any timeblock
            # that is both a default venue for its content type and marked as automatic.
            can_be_automatically_scheduled = any(
                time_block.automatic and time_block.default for time_block in occurrence.time_blocks()
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
            available_venues_query = available_venues_query.filter(
                and_(TimeBlock.automatic, TimeBlock.default)
            )
        case "manual":
            available_venues_query = available_venues_query.filter(
                not_(and_(TimeBlock.automatic, TimeBlock.default))
            )

    available_venues = available_venues_query.group_by(Venue.id).all()
    available_time = get_available_proposal_time(schedule_item_type, estimate_type)

    # We do not need changeover time at the end of a block because blocks are
    # placed to ensure the amount of time required is between them, so correct
    # for over-estimation by occurrences always taking it into account
    changeover_time = SLOT_DURATION * EVENT_SPACING[schedule_item_type]
    end_slot_correction = changeover_time * len(get_blocks_for_type(schedule_item_type, estimate_type))
    allocated_time -= end_slot_correction

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
