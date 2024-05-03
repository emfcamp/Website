from dataclasses import dataclass
from datetime import timedelta
from models.cfp import (
    Proposal,
    Venue,
    get_available_proposal_minutes,
    get_days_map,
    ROUGH_LENGTHS,
    EVENT_SPACING,
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


# TODO: move this somewhere more sensible
CHANGEOVER_PERIOD = 10  # minutes


def get_cfp_estimate(proposal_type: str) -> CFPEstimate:
    """Calculate estimated scheduling capacity statistics for a given proposal type."""
    if proposal_type not in ["talk", "workshop", "performance", "youthworkshop"]:
        raise ValueError(f"Invalid proposal type: {proposal_type}")

    accepted_proposals = (
        Proposal.query_accepted().filter(Proposal.type == proposal_type).all()
    )

    allocated_minutes: int = 0
    unknown_lengths: int = 0

    for proposal in accepted_proposals:
        length = None
        if proposal.scheduled_duration:
            length = proposal.scheduled_duration
        else:
            if proposal.length in ROUGH_LENGTHS:
                length = ROUGH_LENGTHS[proposal.length]
            else:
                unknown_lengths += 1
                continue

        # +10 for changeover period
        allocated_minutes += length + (CHANGEOVER_PERIOD * EVENT_SPACING[proposal.type])

    num_days = len(get_days_map().items())

    available_venues = Venue.query.filter(
        Venue.default_for_types.any(proposal_type)
    ).all()

    # Correct for changeover period not being needed at the end of the day
    # Amount of minutes per venue * number of venues - (slot changeover period) from the end
    allocated_minutes = allocated_minutes - (
        (CHANGEOVER_PERIOD * EVENT_SPACING[proposal_type])
        * num_days
        * len(available_venues)
    )
    if allocated_minutes < 0:
        # If there are few slots allocated, stop this from going negative.
        allocated_minutes = 0

    available_minutes = get_available_proposal_minutes()
    remaining_minutes = available_minutes[proposal_type] - allocated_minutes

    return CFPEstimate(
        proposal_type=proposal_type,
        accepted_count=len(accepted_proposals),
        available_time=timedelta(minutes=available_minutes[proposal_type]),
        allocated_time=timedelta(minutes=allocated_minutes),
        remaining_time=timedelta(minutes=remaining_minutes),
        unknown_lengths=unknown_lengths,
        venues=available_venues,
    )
