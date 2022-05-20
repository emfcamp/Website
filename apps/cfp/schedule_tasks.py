""" CLI commands for scheduling """

import click
from flask import current_app as app
from sqlalchemy import func

from main import db
from models.cfp import Proposal, Venue
from models.village import Village
from apps.cfp_review.base import send_email_for_proposal
from .scheduler import Scheduler
from . import cfp
from ..common.email import from_email


@cfp.cli.command("create_venues")
def create_venues():
    """Create venues defined in code"""
    venues = [
        ("Stage A", 100, (52.03961, -2.37787), True, "talk"),
        ("Stage B", 99, (52.04190, -2.37664), True, "talk,performance"),
        ("Stage C", 98, (52.04050, -2.37765), True, "talk"),
        ("Workshop 1", 97, (52.04259, -2.37515), True, "workshop"),
        ("Workshop 2", 96, (52.04208, -2.37715), True, "workshop"),
        ("Workshop 3", 95, (52.04129, -2.37578), True, "workshop"),
        ("Workshop 4", 94, (52.04329, -2.37590), True, "workshop"),
        ("Youth Workshop", 93, (52.04117, -2.37771), True, "youthworkshop"),
        ("Main Bar", 92, (52.04180, -2.37727), False, "talk,performance"),
        (
            "Lounge",
            91,
            (52.04147, -2.37644),
            False,
            "talk,performance,workshop,youthworkshop",
        ),
    ]
    for name, priority, latlon, scheduled_content_only, type_str in venues:
        venue = Venue.query.filter_by(name=name).all()

        if len(venue) == 1 and venue[0].lat is None:
            venue[0].lat = latlon[0]
            venue[0].lon = latlon[1]
            app.logger.info(f"Updating venue {name} with new latlon")
            continue
        elif venue:
            app.logger.info(f"Venue {name} already exists")
            continue

        venue = Venue(
            name=name,
            type=type_str,
            priority=priority,
            lat=latlon[0],
            lon=latlon[0],
            scheduled_content_only=scheduled_content_only,
        )
        db.session.add(venue)
        app.logger.info(f"Adding venue {name} with type {type_str}")

    db.session.commit()


@cfp.cli.command("create_village_venues")
def create_village_venues():
    for village in Village.query.all():
        venue = Venue.query.filter_by(village_id=village.id).first()
        if venue:
            if venue.name != village.name:
                app.logger.info(
                    f"Updating village venue name from {venue.name} to {village.name}"
                )
                venue.name = village.name
                db.session.commit()

            continue

        if Venue.query.filter(
            func.lower(Venue.name) == func.trim(func.lower(village.name))
        ).count():
            app.logger.warning(
                f"Not creating village venue with colliding name {village.name}"
            )
            continue

        venue = Venue(
            name=village.name, village_id=village.id, scheduled_content_only=False
        )
        db.session.add(venue)
        db.session.commit()


@cfp.cli.command("set_rough_durations")
def set_rough_durations():
    """Assign durations to proposals based on the proposed length."""
    scheduler = Scheduler()
    scheduler.set_rough_durations()


@cfp.cli.command("schedule")
@click.option(
    "-p", "--persist", is_flag=True, help="Persist changes rather than doing a dry run"
    "--ignore_potential", is_flag=True, help="Ignore potential slots when scheduling"
)
def run_schedule(persist, ignore_potential):
    """Run the schedule constraint solver. This can take a while."""
    scheduler = Scheduler()
    if ignore_potential:
        app.logger.info(f"Ignoring current potential slots, items without a scheduled slot will move!")

    scheduler.run(persist, ignore_potential)


@cfp.cli.command("apply_potential_schedule")
@click.option(
    "--email/--no-email", default=True, help="Send update emails to proposers"
)
def apply_potential_schedule(email):
    proposals = (
        Proposal.query.filter(
            (Proposal.potential_venue != None)  # noqa: E711
            | (Proposal.potential_time != None)  # noqa: E711
        )
        .filter(Proposal.scheduled_duration.isnot(None))
        .filter(Proposal.state.in_(["accepted", "finished"]))
        .all()
    )

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
            app.logger.info(
                'Scheduling proposal "%s" by %s', proposal.title, user.email
            )
            if email:
                send_email_for_proposal(
                    proposal,
                    reason="scheduled",
                    from_address=from_email("SPEAKERS_EMAIL"),
                )
        else:
            app.logger.info('Moving proposal "%s" by %s', proposal.title, user.email)
            if email:
                send_email_for_proposal(
                    proposal, reason="moved", from_address=from_email("SPEAKERS_EMAIL")
                )

        db.session.commit()
