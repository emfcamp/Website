from collections import defaultdict
from datetime import datetime, timedelta

from flask import render_template, request

from models import event_start, event_end
from models.cfp import Proposal

from . import cfp_review, review_required


def not_sensible_reasons(
    proposal: Proposal, proposals_by_speaker: dict[int, set[Proposal]]
) -> dict[str, str]:
    reasons = {}

    # -- Proposal (is accepted/finalised and) does not have a proposed or scheduled time.
    if proposal.potential_time is None and proposal.scheduled_time is None:
        reasons["not_scheduled"] = "No proposed or scheduled time"

    # -- Proposal does not have a duration.
    if proposal.scheduled_duration is None:
        reasons["no_duration"] = "No scheduled duration set"

    # -- Proposal is in no venue.
    if proposal.potential_time is not None and proposal.potential_venue is None:
        reasons["proposed_without_venue"] = "Proposed time set, but no venue allocated"
    if proposal.scheduled_time is not None and proposal.scheduled_venue is None:
        reasons["scheduled_without_venue"] = "Scheduled time set, but no venue allocated"

    # -- Proposal is in a venue that is not in the allowed list for that type of content.
    if proposal.potential_venue is not None:
        if proposal.type not in proposal.potential_venue.allowed_types:
            reasons["proposed_venue_illegal"] = (
                f'{proposal.type} proposed to be in "{proposal.potential_venue.name}", which admits content of types: {proposal.potential_venue.allowed_types}'
            )
    if proposal.scheduled_venue is not None:
        if proposal.type not in proposal.scheduled_venue.allowed_types:
            reasons["scheduled_venue_illegal"] = (
                f'{proposal.type} scheduled to be in "{proposal.scheduled_venue.name}", which admits content of types: {proposal.scheduled_venue.allowed_types}'
            )

    # -- Proposal has allowed time periods that are after 2am or before 9am.
    for n, period in enumerate(proposal.get_allowed_time_periods()):

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

        # -- Proposal is before Wednesday 12 noon, or after Sunday 2am.
        if t < sensible_start:
            reasons[reason_key] = (
                f"{note} time ({t.strftime(human_format)}) is before {sensible_start.strftime(human_format)}"
            )
        elif t > sensible_end:
            reasons[reason_key] = (
                f"{note} time ({t.strftime(human_format)}) is after {sensible_end.strftime(human_format)}"
            )

        # -- Proposal is after 2am or before 9am.
        if t.hour >= 2 and t.hour < 9:
            reasons[f"{reason_key}_quiet"] = (
                f"{note} is scheduled between 2am and 9am ({t.strftime(human_format)})"
            )

        # -- Proposal lies outside the allowed time periods.
        permitted_time = False
        for n, period in enumerate(proposal.get_allowed_time_periods()):
            if t >= period.start and t <= period.end:
                permitted_time = True

        if not permitted_time:
            reasons[f"{reason_key}_outside_allowed_times"] = (
                f"{note} is outside allowed proposal time periods"
            )

    _check_timing(proposal.potential_time, "Proposed start", "proposed_start")
    _check_timing(proposal.scheduled_time, "Scheduled start", "scheduled_start")
    _check_timing(proposal.potential_end_date, "Proposed end", "proposed_end")
    _check_timing(proposal.end_date, "Scheduled end", "scheduled_end")

    # -- Proposal overlaps another one by the same user.
    def _talk_ranges(p: Proposal) -> dict[str, tuple[datetime, datetime]]:
        ranges = {}
        if p.potential_time and p.potential_end_date:
            ranges["proposed"] = (p.potential_time, p.potential_end_date)
        if p.scheduled_time and p.end_date:
            ranges["scheduled"] = (p.scheduled_time, p.end_date)
        return ranges

    talk_ranges = _talk_ranges(proposal)
    for other_proposal in proposals_by_speaker[proposal.user_id]:
        if other_proposal == proposal:
            continue
        other_ranges = _talk_ranges(other_proposal)
        for this_type, (this_start, this_end) in talk_ranges.items():
            for other_type, (other_start, other_end) in other_ranges.items():
                if max(this_start, other_start) < min(this_end, other_end):
                    # Overlap.
                    reasons[f"{this_type}_overlap_{other_proposal.id}_{other_type}"] = (
                        f"The {this_type} time ({this_start} > {this_end}) overlaps with a {other_proposal.type} by same user: {other_proposal.display_title}'s {other_type} time ({other_start} > {other_end})"
                    )

    return reasons


@cfp_review.route("/sense-check")
@review_required
def sense_check():
    types_to_show = request.args.getlist("type")
    if not types_to_show:
        types_to_show = ["talk", "workshop", "youthworkshop", "performance"]

    accepted_proposals = (
        Proposal.query_accepted(include_user_scheduled=False)
        .filter(Proposal.type.in_(types_to_show))
        .order_by(Proposal.type)
        .all()
    )

    proposals_for_overlap = (
        Proposal.query_accepted(include_user_scheduled=False)
        .filter(Proposal.type.in_(["talk", "workshop", "youthworkshop", "performance"]))
        .all()
    )
    proposals_by_speaker = defaultdict(set)
    for proposal in proposals_for_overlap:
        proposals_by_speaker[proposal.user_id].add(proposal)

    not_sensible_proposals = []
    for accepted_proposal in accepted_proposals:
        if reasons := not_sensible_reasons(accepted_proposal, proposals_by_speaker):
            not_sensible_proposals.append((accepted_proposal, reasons))

    return render_template(
        "cfp_review/sense_check.html",
        not_sensible_proposals=not_sensible_proposals,
        proposals_count=len(accepted_proposals),
    )
