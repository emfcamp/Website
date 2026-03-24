"""CLI commands for scheduling"""

from dataclasses import dataclass
from typing import Literal

import click
from flask import current_app as app
from sqlalchemy import func, or_, select

from apps.cfp_review.base import send_email_for_proposal
from main import db
from models.cfp import Occurrence, Proposal, ScheduleItem, ScheduleItemType, Venue
from models.village import Village

from . import cfp
from .scheduler import Scheduler


@dataclass
class VenueDefinition:
    name: str
    priority: int
    latlon: tuple[float, float]
    allows_attendee_content: bool
    allowed_types: list[str]
    default_for_types: list[str]
    capacity: int | None

    @property
    def location(self) -> str:
        return f"POINT({self.latlon[1]} {self.latlon[0]})"

    def as_venue(self) -> Venue:
        return Venue(
            name=self.name,
            priority=self.priority,
            location=self.location,
            allows_attendee_content=self.allows_attendee_content,
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
        allows_attendee_content=False,
        allowed_types=["talk"],
        default_for_types=["talk"],
        capacity=1000,
    ),
    VenueDefinition(
        name="Stage B",
        priority=99,
        latlon=(52.04190, -2.37664),
        allows_attendee_content=False,
        allowed_types=["talk", "performance"],
        default_for_types=["talk", "performance", "lightning"],
        capacity=600,
    ),
    VenueDefinition(
        name="Stage C",
        priority=98,
        latlon=(52.04050, -2.37765),
        allows_attendee_content=False,
        allowed_types=["talk"],
        default_for_types=["talk", "lightning"],
        capacity=450,
    ),
    VenueDefinition(
        name="Workshop 1",
        priority=97,
        latlon=(52.04259, -2.37515),
        allows_attendee_content=False,
        allowed_types=["workshop"],
        default_for_types=["workshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Workshop 2",
        priority=96,
        latlon=(52.04208, -2.37715),
        allows_attendee_content=False,
        allowed_types=["workshop"],
        default_for_types=["workshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Workshop 3",
        priority=95,
        latlon=(52.04129, -2.37578),
        allows_attendee_content=False,
        allowed_types=["workshop"],
        default_for_types=["workshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Workshop 4",
        priority=94,
        latlon=(52.04329, -2.37590),
        allows_attendee_content=False,
        allowed_types=["workshop"],
        default_for_types=["workshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Workshop 5",
        priority=93,
        latlon=(52.040938, -2.37706),
        allows_attendee_content=False,
        allowed_types=["workshop"],
        default_for_types=["workshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Youth Workshop",
        priority=92,
        latlon=(52.04117, -2.37771),
        allows_attendee_content=False,
        allowed_types=["youthworkshop"],
        default_for_types=["youthworkshop"],
        capacity=30,
    ),
    VenueDefinition(
        name="Main Bar",
        priority=91,
        latlon=(52.04180, -2.37727),
        allows_attendee_content=True,
        allowed_types=["talk", "performance"],
        default_for_types=[],
        capacity=None,
    ),
    VenueDefinition(
        name="Lounge",
        priority=90,
        latlon=(52.04147, -2.37644),
        allows_attendee_content=True,
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
        if venue:
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

        venue = Venue(name=village.name, village_id=village.id, allows_attendee_content=True)
        db.session.add(venue)
        db.session.commit()


@cfp.cli.command("set_rough_durations")
def set_rough_durations():
    """
    Assign durations to occurrences based on the proposed length.
    This is what allows them to be sent the "please finalise" email,
    and to be scheduled.
    """
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
        app.logger.info("Ignoring current potential slots, items without a scheduled slot will move!")

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
    help="Which type of proposal to apply for ('all' selects all schedule items)",
    required=True,
)
def apply_potential_schedule(email: bool, type: ScheduleItemType | Literal["all"]) -> None:
    app.logger.info(f"Apply schedule for {type} type(s)")
    if not type:
        raise Exception("Set a type")

    query = (
        select(Occurrence)
        .where(Occurrence.scheduled_duration.isnot(None))
        .where(
            or_(
                # TODO: when would these ever not be set together?
                Occurrence.potential_venue_id.isnot(None),
                Occurrence.potential_time.isnot(None),
            )
        )
        .where(Occurrence.proposal.has(Proposal.state.in_({"accepted", "finalised"})))
    )

    if type != "all":
        query = query.where(Occurrence.schedule_item.has(ScheduleItem.type == type))

    occurrences: list[Occurrence] = list(db.session.scalars(query))

    app.logger.info(f"Got {len(occurrences)} occurrences")

    newly_scheduled_schedule_items = []
    moved_schedule_items = []

    for occurrence in occurrences:
        user = occurrence.user

        # TODO: when would these ever not be set together?
        if occurrence.potential_venue:
            occurrence.scheduled_venue = occurrence.potential_venue
            occurrence.potential_venue = None

        if occurrence.potential_time:
            occurrence.scheduled_time = occurrence.potential_time
            occurrence.potential_time = None

        if occurrence.state == "unscheduled" and occurrence.scheduled_venue and occurrence.scheduled_time:
            occurrence.state = "scheduled"

            app.logger.info('Scheduled occurrence for "%s" by %s', occurrence.schedule_item.title, user.email)
            newly_scheduled_schedule_items.append(occurrence.schedule_item)

        elif occurrence.state == "scheduled":
            app.logger.info('Moved occurrence for "%s" by %s', occurrence.schedule_item.title, user.email)
            moved_schedule_items.append(occurrence.schedule_item)

        else:
            # TODO: not fully scheduled yet. When would this ever happen?
            pass

    if email:
        # Only send one email per schedule item, except in the unlikely case where
        # they have one occurrence that's been scheduled and one that's been moved
        for schedule_item in newly_scheduled_schedule_items:
            # We filter on Occurrence.proposal.has() above
            assert schedule_item.proposal is not None
            send_email_for_proposal(schedule_item.proposal, reason="slot-scheduled")
        for schedule_item in moved_schedule_items:
            # We filter on Occurrence.proposal.has() above
            assert schedule_item.proposal is not None
            send_email_for_proposal(schedule_item.proposal, reason="slot-moved")

    db.session.commit()
