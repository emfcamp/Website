from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from models.cfp import (
    PROPOSAL_TIMESLOTS,
    Proposal,
    Venue,
    get_days_map,
    ROUGH_LENGTHS,
    EVENT_SPACING,
    SLOT_LENGTH,
    make_periods_contiguous,
    timeslot_to_period,
)


@dataclass
class CFPEstimate:
    proposal_type: str
    # The number of proposals currently accepted
    accepted_count: int
    available_time: timedelta
    allocated_time: timedelta
    remaining_time: timedelta
    unknown_lengths: int
    venues: list[Venue]


def get_available_proposal_minutes():
    minutes = defaultdict(int)
    venue_names_by_type = Venue.emf_venue_names_by_type()
    for type, slots in PROPOSAL_TIMESLOTS.items():
        periods = make_periods_contiguous([timeslot_to_period(ts, type=type) for ts in slots])
        for period in periods:
            minutes[type] += int((period.end - period.start).total_seconds() / 60) * len(
                venue_names_by_type[type]
            )
    return minutes


def get_cfp_estimate(proposal_type: str) -> CFPEstimate:
    """Calculate estimated scheduling capacity statistics for a given proposal type."""
    if proposal_type not in ["talk", "workshop", "performance", "youthworkshop"]:
        raise ValueError(f"Invalid proposal type: {proposal_type}")

    changeover_time = SLOT_LENGTH * EVENT_SPACING[proposal_type]

    accepted_proposals = Proposal.query_accepted().filter(Proposal.type == proposal_type).all()

    allocated_time = timedelta()
    unknown_lengths: int = 0

    for proposal in accepted_proposals:
        length = None
        if proposal.scheduled_duration:
            length = timedelta(minutes=proposal.scheduled_duration)
        else:
            if proposal.length in ROUGH_LENGTHS:
                length = timedelta(minutes=ROUGH_LENGTHS[proposal.length])
            else:
                unknown_lengths += 1
                continue

        allocated_time += length + changeover_time

    num_days = len(get_days_map().items())

    available_venues = Venue.query.filter(Venue.default_for_types.any(proposal_type)).all()

    # Correct for changeover period not being needed at the end of the day
    # This can go negative if there aren't many proposals accepted yet, so clamp to 0
    changeover_correction = changeover_time * num_days * len(available_venues)
    allocated_time = max(allocated_time - changeover_correction, timedelta(0))

    available_minutes = get_available_proposal_minutes()
    available_time = timedelta(minutes=available_minutes[proposal_type])

    return CFPEstimate(
        proposal_type=proposal_type,
        accepted_count=len(accepted_proposals),
        available_time=available_time,
        allocated_time=allocated_time,
        remaining_time=available_time - allocated_time,
        unknown_lengths=unknown_lengths,
        venues=available_venues,
    )
