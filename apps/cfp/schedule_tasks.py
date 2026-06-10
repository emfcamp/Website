"""CLI commands for scheduling"""

import click
from flask import current_app as app

from main import db
from models.content import ScheduleItemType

from . import cfp
from .scheduler import Scheduler


@cfp.cli.command("schedule")
@click.option("--type", help="Only run the scheduler for the specified type of content.")
def run_schedule(type: ScheduleItemType | None) -> None:
    """Run the schedule constraint solver. This can take a while."""
    scheduler = Scheduler()

    if type:
        app.logger.info(f"Only scheduling {type} proposals.")
        types: list[ScheduleItemType] = [type]
    else:
        types = ["talk", "workshop", "familyworkshop"]

    potential_schedule = scheduler.run(types)
    db.session.add(potential_schedule)
    db.session.commit()
