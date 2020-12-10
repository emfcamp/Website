""" CLI commands for scheduling """

import click
from flask import current_app as app

from main import db
from models.cfp import Proposal, Venue

from apps.cfp_review.base import send_email_for_proposal
from .scheduler import Scheduler
from . import cfp


@cfp.cli.command("create_venues")
def create_venues():
    """ Create venues defined in code """
    venues = [
        ("Stage A", ["talk"], 100, (52.0396099, -2.377866)),
        ("Stage B", ["talk", "performance"], 99, (52.0418968, -2.3766391)),
        ("Stage C", ["talk"], 98, (52.040485, -2.3776549)),
        ("Workshop 1", ["workshop"], 97, (52.04161469, -2.37593613)),
        ("Workshop 2", ["workshop"], 96, (52.04080079, -2.3780661)),
        ("Workshop 3", ["workshop"], 95, (52.0406851, -2.3780847)),
        ("Workshop 4", ["workshop"], 94, (52.0417884, -2.37586151)),
        ("Youth Workshop", ["youthworkshop"], 93, (52.041997, -2.375533)),
    ]
    for name, type, priority, latlon in venues:
        type_str = ",".join(type)
        venue = Venue.query.filter_by(name=name, type=type_str).all()

        if len(venue) == 1 and venue[0].lat is None:
            venue[0].lat = latlon[0]
            venue[0].lon = latlon[1]
            app.logger.info("Updating venue %s with latlon" % name)
            continue
        elif venue:
            continue

        venue = Venue()
        venue.name = name
        venue.type = type_str
        venue.priority = priority
        db.session.add(venue)
        app.logger.info('Adding venue "%s" as type "%s"' % (name, type))

    db.session.commit()


@cfp.cli.command("set_rough_durations")
def set_rough_durations():
    """ Assign durations to proposals based on the proposed length. """
    scheduler = Scheduler()
    scheduler.set_rough_durations()


@cfp.cli.command("schedule")
@click.option(
    "-p", "--persist", is_flag=True, help="Persist changes rather than doing a dry run"
)
def run_schedule(persist):
    """ Run the schedule constraint solver. This can take a while. """
    scheduler = Scheduler()
    scheduler.run(persist)


@cfp.cli.command("apply_potential_schedule")
def apply_potential_schedule():
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

        ok = False
        if previously_unscheduled:
            app.logger.info(
                'Scheduling proposal "%s" by %s', proposal.title, user.email
            )
            ok = send_email_for_proposal(
                proposal, reason="scheduled", from_address=app.config["SPEAKERS_EMAIL"]
            )
        else:
            app.logger.info('Moving proposal "%s" by %s', proposal.title, user.email)
            ok = send_email_for_proposal(
                proposal, reason="moved", from_address=app.config["SPEAKERS_EMAIL"]
            )

        if ok:
            db.session.commit()
        else:
            raise Exception("Error when messaging user when applying schedule")
