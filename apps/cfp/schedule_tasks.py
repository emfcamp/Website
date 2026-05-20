"""CLI commands for scheduling"""

import click
from flask import current_app as app

from main import db
from models.content import ScheduleItemType

from . import cfp
from .scheduler import Scheduler


@cfp.cli.command("set_rough_durations")
def set_rough_durations():
    """
    Assign durations to occurrences based on the proposed length.
    This is what allows them to be sent the "please finalise" email,
    and to be scheduled.
    """
    scheduler = Scheduler()
    scheduler.set_rough_durations()
    db.session.commit()


@cfp.cli.command("schedule")
@click.option("--type", help="Only run the scheduler for the specified type of content.")
def run_schedule(type: ScheduleItemType | None) -> None:
    """Run the schedule constraint solver. This can take a while."""
    scheduler = Scheduler()

    if type:
        app.logger.info(f"Only scheduling {type} proposals.")
        types: list[ScheduleItemType] = [type]
    else:
        types = ["talk", "workshop", "youthworkshop"]

    potential_schedule = scheduler.run(types)
    db.session.add(potential_schedule)
    db.session.commit()


""" @cfp.cli.command("apply_potential_schedule")
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
 """
