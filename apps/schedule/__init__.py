"""
    Schedule App

    This app displays what talks are happening from the CfP system. A deceptively complex task.
    The schedule for an event can be in one of four modes:

        * There's no schedule yet, why not look at previous years'?
        * There are talks accepted, but they aren't scheduled yet - show them in a list
          and maybe let the user favourite them to assist our scheduling algorithm.
        * There's actually a schedule and you should probably work out which talks you're going to.
        * The event has finished, and we're displaying an archived schedule.

    ## Configuration Flags

    The schedule app uses two configuration flags to determine how to render the schedule
    for the current event (these don't affect historic events).

        * `LINE_UP = True` indicates that the approved talks should be displayed as a list
        * `SCHEDULE = True` indicates that the full schedule browser should be displayed

    If neither of these flags are enabled, links will be displayed to schedules for previous
    events.
"""
import pytz
from flask import Blueprint, redirect, url_for, abort

from models import event_year

schedule = Blueprint("schedule", __name__)
event_tz = pytz.timezone("Europe/London")


# The routes below are here to redirect from various ill-thought-through old URL schemes
@schedule.route("/talks")
@schedule.route("/line-up")
def line_up_redirect():
    return redirect(url_for(".main"), 301)


@schedule.route("/talks/<int:year>")
@schedule.route("/line-up/<int:year>")
def line_up_year_redirect(year):
    return redirect(url_for(".main_year", year=year), 301)


@schedule.route("/talks/<int:year>/<int:proposal_id>")
@schedule.route("/talks/<int:year>/<int:proposal_id>-<string:slug>")
@schedule.route("/line-up/<int:year>/<int:proposal_id>")
@schedule.route("/line-up/<int:year>/<int:proposal_id>-<string:slug>")
def lineup_talk_redirect(year, proposal_id, slug=None):
    return redirect(
        url_for(".item", year=year, proposal_id=proposal_id, slug=slug), 301
    )


@schedule.route("/schedule.<string:fmt>")
def feed_redirect(fmt):
    routes = {
        "json": "schedule.schedule_json",
        "frab": "schedule.schedule_frab",
        "ical": "schedule.schedule_ical",
        "ics": "schedule.schedule_ical",
    }

    if fmt not in routes:
        abort(404)
    return redirect(url_for(routes[fmt], year=event_year()))


from . import base  # noqa
from . import feeds  # noqa
from . import attendee_content  # noqa

