from collections import defaultdict
from datetime import datetime, timedelta
from typing import TypeGuard, get_args

from flask import render_template, request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from models import event_start, event_end
from models.cfp import Occurrence, ScheduleItem, ScheduleItemType

from . import cfp_review, review_required
from main import db


def not_sensible_reasons(
    occurrence: Occurrence, occurrences_by_speaker: dict[int, set[Occurrence]]
) -> dict[str, str]:
    reasons = {}

    # -- Occurrence does not have a proposed or scheduled time.
    if occurrence.potential_time is None and occurrence.scheduled_time is None:
        reasons["not_scheduled"] = "No proposed or scheduled time"

    # -- Occurrence does not have a duration.
    if occurrence.scheduled_duration is None:
        reasons["no_duration"] = "No scheduled duration set"

    # -- Occurrence is in no venue.
    if occurrence.potential_time is not None and occurrence.potential_venue is None:
        reasons["proposed_without_venue"] = "Proposed time set, but no venue allocated"
    if occurrence.scheduled_time is not None and occurrence.scheduled_venue is None:
        reasons["scheduled_without_venue"] = "Scheduled time set, but no venue allocated"

    # -- Occurrence is in a venue that is not in the allowed list for that type of content.
    if occurrence.potential_venue is not None:
        if occurrence.schedule_item.type not in occurrence.potential_venue.allowed_types:
            reasons["proposed_venue_illegal"] = (
                f'{occurrence.schedule_item.type} proposed to be in "{occurrence.potential_venue.name}", '
                f"which admits content of types: {occurrence.potential_venue.allowed_types}"
            )
    if occurrence.scheduled_venue is not None:
        if occurrence.schedule_item.type not in occurrence.scheduled_venue.allowed_types:
            reasons["scheduled_venue_illegal"] = (
                f'{occurrence.schedule_item.type} scheduled to be in "{occurrence.scheduled_venue.name}", '
                f"which admits content of types: {occurrence.scheduled_venue.allowed_types}"
            )

    # -- Occurrence has allowed time periods that are after 2am or before 9am.
    for n, period in enumerate(occurrence.get_allowed_time_periods()):

        def reason_key(reason):
            return f"period_{n}_{reason}"

        if period.start >= period.end:
            reasons[reason_key("starts_after_end")] = (
                f'Allowed time period "{period.start} > {period.end}" starts after it ends.'
            )
            continue

        period_length = period.end - period.start
        if period_length.total_seconds() > (60 * 60 * 24 - (9 - 2)):
            # If the time period is greater than 24-(9-2) hours, then by necessity it overlaps a 2am-9am quiet period.
            reasons[reason_key("too_long")] = (
                f'Allowed time period "{period.start} > {period.end}" overlaps 2am-9am quiet period (time period too long)'
            )
        elif period.start.hour >= 2 and period.start.hour < 9:
            # Start time lies within quiet period
            reasons[reason_key("starts_in_quiet")] = (
                f'Allowed time period "{period.start} > {period.end}" overlaps 2am-9am quiet period (start is between 2am and 9am)'
            )
        elif period.end.hour >= 2 and period.end.hour < 9:
            # End time lies within quiet period
            reasons[reason_key("ends_in_quiet")] = (
                f'Allowed time period "{period.start} > {period.end}" overlaps 2am-9am quiet period (end is between 2am and 9am)'
            )
        elif period.start.hour < 2 and period.end.hour >= 9:
            # Start time before quiet period, end time after quiet period
            reasons[reason_key("same_day_subsumes_quiet")] = (
                f'Allowed time period "{period.start} > {period.end}" overlaps 2am-9am quiet period (starts before 2am and ends after 9am)'
            )
        elif period.start.hour > period.end.hour and period.end.hour >= 9:
            # If the start hour is after the end hour, then they must be on different days.
            reasons[reason_key("different_day_subsumes_quiet")] = (
                f'Allowed time period "{period.start} > {period.end}" overlaps 2am-9am quiet period (starts on previous day and ends after 9am)'
            )

    # Assumption: EVENT_START and EVENT_END are the right day (Wednesday and Sunday).
    human_format = "%a %d, %H:%M (%Y-%m-%d %H:%M:%S)"
    sensible_start = event_start().replace(hour=12, minute=0, second=0, microsecond=0)
    # We'll need to step event_end forward by a day to land on Monday.
    sensible_end = (event_end() + timedelta(days=1)).replace(hour=2, minute=0, second=0, microsecond=0)

    def _check_timing(t, note, reason_key):
        if not t:
            return

        # -- Occurrence is before Wednesday 12 noon, or after Sunday 2am.
        if t < sensible_start:
            reasons[reason_key] = (
                f"{note} time ({t.strftime(human_format)}) is before {sensible_start.strftime(human_format)}"
            )
        elif t > sensible_end:
            reasons[reason_key] = (
                f"{note} time ({t.strftime(human_format)}) is after {sensible_end.strftime(human_format)}"
            )

        # -- Occurrence is after 2am or before 9am.
        if t.hour >= 2 and t.hour < 9:
            reasons[f"{reason_key}_quiet"] = (
                f"{note} is scheduled between 2am and 9am ({t.strftime(human_format)})"
            )

        # -- Occurrence lies outside the allowed time periods.
        permitted_time = False
        for n, period in enumerate(occurrence.get_allowed_time_periods()):
            if t >= period.start and t <= period.end:
                permitted_time = True

        if not permitted_time:
            reasons[f"{reason_key}_outside_allowed_times"] = (
                f"{note} is outside allowed occurrence time periods"
            )

    _check_timing(occurrence.potential_time, "Proposed start", "proposed_start")
    _check_timing(occurrence.scheduled_time, "Scheduled start", "scheduled_start")
    _check_timing(occurrence.potential_end_time, "Proposed end", "proposed_end")
    _check_timing(occurrence.scheduled_end_time, "Scheduled end", "scheduled_end")

    # -- Occurrence overlaps another one by the same user.
    def get_occurrence_ranges(occurrence: Occurrence) -> dict[str, tuple[datetime, datetime]]:
        ranges = {}
        if occurrence.potential_time and occurrence.potential_end_time:
            ranges["proposed"] = (occurrence.potential_time, occurrence.potential_end_time)
        if occurrence.scheduled_time and occurrence.scheduled_end_time:
            ranges["scheduled"] = (occurrence.scheduled_time, occurrence.scheduled_end_time)
        return ranges

    occurrence_ranges = get_occurrence_ranges(occurrence)
    for other_occurrence in occurrences_by_speaker[occurrence.schedule_item.user_id]:
        if other_occurrence == occurrence:
            continue
        other_ranges = get_occurrence_ranges(other_occurrence)
        for this_type, (this_start, this_end) in occurrence_ranges.items():
            for other_type, (other_start, other_end) in other_ranges.items():
                if max(this_start, other_start) < min(this_end, other_end):
                    # Overlap.
                    reasons[f"{this_type}_overlap_{other_occurrence.id}_{other_type}"] = (
                        f"The {this_type} time ({this_start} > {this_end}) overlaps with a "
                        f"{other_occurrence.schedule_item.type} by same user: {other_occurrence.schedule_item.title}'s "
                        f"{other_type} time ({other_start} > {other_end})"
                    )

    return reasons


@cfp_review.route("/sense-check")
@review_required
def sense_check():
    types_to_show = request.args.getlist("type")
    if not types_to_show:
        types_to_show = ["talk", "workshop", "youthworkshop", "performance"]

    def validate_types(types: list[str]) -> TypeGuard[list[ScheduleItemType]]:
        invalid_types = {t for t in types_to_show if t not in get_args(ScheduleItemType)}
        if invalid_types:
            raise ValueError(f"Invalid schedule item types: {', '.join(invalid_types)}")
        return True

    assert validate_types(types_to_show)

    def get_occurrences_for_types(types: list[ScheduleItemType]):
        return list(
            db.session.scalars(
                select(Occurrence)
                .join(Occurrence.schedule_item)
                .options(selectinload(Occurrence.schedule_item))
                .where(ScheduleItem.type.in_(types))
                .order_by(ScheduleItem.type, ScheduleItem.id, Occurrence.id)
            )
        )

    occurrences = get_occurrences_for_types(types_to_show)
    # FIXME: why is this not all types?
    occurrences_for_overlap = get_occurrences_for_types(["talk", "workshop", "youthworkshop", "performance"])

    occurrences_by_speaker = defaultdict(set)
    for occurrence in occurrences_for_overlap:
        occurrences_by_speaker[occurrence.schedule_item.user_id].add(occurrence)

    not_sensible_occurrences = []
    for occurrence in occurrences:
        if reasons := not_sensible_reasons(occurrence, occurrences_by_speaker):
            not_sensible_occurrences.append((occurrence, reasons))

    return render_template(
        "cfp_review/sense_check.html",
        not_sensible_occurrences=not_sensible_occurrences,
        occurrence_count=len(occurrences),
    )
