"""CLI commands for scheduling"""

import click
from dataclasses import dataclass
from flask import current_app as app
from sqlalchemy import func

from main import db
from models.cfp import Proposal, Venue
from models.village import Village
from apps.cfp_review.base import send_email_for_proposal
from .scheduler import Scheduler
from . import cfp
from ..common.email import from_email


@dataclass
class VenueDefinition:
    name: str
    priority: int
    latlon: tuple[float, float]
    scheduled_content_only: bool
    allowed_types: list[str]
    default_for_types: list[str]
    capacity: int | None

    @property
    def location(self) -> str:
        if self.latlon:
            return f"POINT({self.latlon[1]} {self.latlon[0]})"
        else:
            return None

    def as_venue(self) -> Venue:
        return Venue(
            name=self.name,
            priority=self.priority,
            location=self.location,
            scheduled_content_only=self.scheduled_content_only,
            allowed_types=self.allowed_types,
            default_for_types=self.default_for_types,
            capacity=self.capacity,
        )


# This lives only here, on purpose, because this is just intended to seed the DB.
_EMF_VENUES = [
    VenueDefinition(
        name="Stage A",
        priority=100,
        latlon=(52.03961, -2.37787),
        scheduled_content_only=True,
        allowed_types=["talk"],
        default_for_types=["talk"],
        capacity=1000,
    ),
    VenueDefinition(
        name="Stage B",
        priority=99,
        latlon=(52.04190, -2.37664),
        scheduled_content_only=True,
        allowed_types=["talk", "performance"],
        default_for_types=["talk", "performance", "lightning"],
        capacity=600,
    ),
    VenueDefinition(
        name="Stage C",
        priority=98,
        latlon=(52.04050, -2.37765),
        scheduled_content_only=True,
        allowed_types=["talk"],
        default_for_types=["talk", "lightning"],
        capacity=450,
    ),
    VenueDefinition(
        name="Workshop 1",
        priority=97,
        latlon=(52.04259, -2.37515),
        scheduled_content_only=True,
        allowed_types=["workshop"],
        default_for_types=["workshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Workshop 2",
        priority=96,
        latlon=(52.04208, -2.37715),
        scheduled_content_only=True,
        allowed_types=["workshop"],
        default_for_types=["workshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Workshop 3",
        priority=95,
        latlon=(52.04129, -2.37578),
        scheduled_content_only=True,
        allowed_types=["workshop"],
        default_for_types=["workshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Workshop 4",
        priority=94,
        latlon=(52.04329, -2.37590),
        scheduled_content_only=True,
        allowed_types=["workshop"],
        default_for_types=["workshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Workshop 5",
        priority=93,
        latlon=(52.040938, -2.37706),
        scheduled_content_only=True,
        allowed_types=["workshop"],
        default_for_types=["workshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Youth Workshop",
        priority=92,
        latlon=(52.04117, -2.37771),
        scheduled_content_only=True,
        allowed_types=["youthworkshop"],
        default_for_types=["youthworkshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Main Bar",
        priority=91,
        latlon=(52.04180, -2.37727),
        scheduled_content_only=False,
        allowed_types=["talk", "performance"],
        default_for_types=[],
        capacity=None,
    ),
    VenueDefinition(
        name="Lounge",
        priority=90,
        latlon=(52.04147, -2.37644),
        scheduled_content_only=False,
        allowed_types=["talk", "performance", "workshop", "youthworkshop"],
        default_for_types=[],
        capacity=None,
    ),
]


@cfp.cli.command("create_venues")
def create_venues():
    """Create venues defined in code"""
    created = updated = 0
    for venue_definition in _EMF_VENUES:
        name = venue_definition.name
        venue = Venue.query.filter_by(name=name).all()

        if len(venue) == 1 and venue[0].location is None:
            venue[0].location = venue_definition.location
            updated += 1
            continue
        elif venue:
            continue

        db.session.add(venue_definition.as_venue())
        created += 1

    db.session.commit()
    app.logger.info(f"Created {created} and updated {updated} venues.")


@cfp.cli.command("create_village_venues")
def create_village_venues():
    for village in Village.query.all():
        venue = Venue.query.filter_by(village_id=village.id).first()
        if venue:
            if venue.name in _EMF_VENUES:
                app.logger.info(f"Not updating EMF venue {venue.name}")

            elif venue.name != village.name:
                app.logger.info(f"Updating village venue name from {venue.name} to {village.name}")
                venue.name = village.name
                db.session.commit()

            continue

        if Venue.query.filter(func.lower(Venue.name) == func.trim(func.lower(village.name))).count():
            app.logger.warning(f"Not creating village venue with colliding name {village.name}")
            continue

        venue = Venue(name=village.name, village_id=village.id, scheduled_content_only=False)
        db.session.add(venue)
        db.session.commit()


@cfp.cli.command("set_rough_durations")
def set_rough_durations():
    """Assign durations to proposals based on the proposed length."""
    scheduler = Scheduler()
    scheduler.set_rough_durations()


@cfp.cli.command("schedule")
@click.option("-p", "--persist", is_flag=True, help="Persist changes rather than doing a dry run")
@click.option("--ignore_potential", is_flag=True, help="Ignore potential slots when scheduling")
@click.option("--type", help="Only run the scheduler for the specified type of content.")
def run_schedule(persist, ignore_potential, type):
    """Run the schedule constraint solver. This can take a while."""
    scheduler = Scheduler()
    if ignore_potential:
        app.logger.info(f"Ignoring current potential slots, items without a scheduled slot will move!")

    if type:
        app.logger.info(f"Only scheduling {type} proposals.")
        type = [type]
    else:
        type = ["talk", "workshop", "youthworkshop"]

    scheduler.run(persist, ignore_potential, type)


@cfp.cli.command("apply_potential_schedule")
@click.option("--email/--no-email", default=True, help="Send update emails to proposers")
@click.option(
    "--type",
    help="Which type of proposal to apply for ('all' selects all proposals)",
    required=True,
)
def apply_potential_schedule(email, type):
    app.logger.info(f"Apply schedule for {type} type(s)")
    if type == "all":
        query = Proposal.query
    elif type:
        query = Proposal.query.filter(Proposal.type == type)
    else:
        raise Exception("Set a type")

    proposals = (
        query.filter(
            (Proposal.potential_venue != None)  # noqa: E711
            | (Proposal.potential_time != None)  # noqa: E711
        )
        .filter(Proposal.scheduled_duration.isnot(None))
        .filter(Proposal.is_accepted)
        .all()
    )

    app.logger.info(f"Got {len(proposals)} proposals")

    for proposal in proposals:
        user = proposal.user

        previously_unscheduled = True
        if proposal.scheduled_venue or proposal.scheduled_time:
            previously_unscheduled = False

        if proposal.potential_venue:
            proposal.scheduled_venue = proposal.potential_venue
            proposal.potential_venue = None

        if proposal.potential_time:
            proposal.scheduled_time = proposal.potential_time
            proposal.potential_time = None

        if previously_unscheduled:
            app.logger.info('Scheduling proposal "%s" by %s', proposal.title, user.email)
            if email:
                send_email_for_proposal(
                    proposal,
                    reason="scheduled",
                    from_address=from_email("SPEAKERS_EMAIL"),
                )
        else:
            app.logger.info('Moving proposal "%s" by %s', proposal.title, user.email)
            if email:
                send_email_for_proposal(proposal, reason="moved", from_address=from_email("SPEAKERS_EMAIL"))

        db.session.commit()
