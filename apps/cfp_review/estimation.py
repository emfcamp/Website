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
CHANGEOVER_PERIOD = timedelta(minutes=10)


def get_cfp_estimate(proposal_type: str) -> CFPEstimate:
    """Calculate estimated scheduling capacity statistics for a given proposal type."""
    if proposal_type not in ["talk", "workshop", "performance", "youthworkshop"]:
        raise ValueError(f"Invalid proposal type: {proposal_type}")

    accepted_proposals = (
        Proposal.query_accepted().filter(Proposal.type == proposal_type).all()
    )

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

        # add changeover period
        allocated_time += length + (CHANGEOVER_PERIOD * EVENT_SPACING[proposal.type])

    num_days = len(get_days_map().items())

    available_venues = Venue.query.filter(
        Venue.default_for_types.any(proposal_type)
    ).all()

    # Correct for changeover period not being needed at the end of the day
    # Amount of minutes per venue * number of venues - (slot changeover period) from the end
    changeover_correction = (
        (CHANGEOVER_PERIOD * EVENT_SPACING[proposal_type])
        * num_days
        * len(available_venues)
    )
    # This can go negative if there aren't many proposals scheduled, so clamp to 0
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
