""" View helpers for displaying historic schedules.

    These are served from static files in this repository as the database is wiped every year.
"""
from flask import render_template, abort, redirect, url_for, send_file
from dateutil.parser import parse as date_parse

from models import event_year
from models.cfp import proposal_slug
from ..common import load_archive_file, archive_file


def abort_if_invalid_year(year):
    if not 2012 <= year < event_year():
        abort(404)


def parse_event(event):
    if "start_date" in event:
        event["start_date"] = date_parse(event["start_date"])

    if "end_date" in event:
        event["end_date"] = date_parse(event["end_date"])

    return event


def item_historic(year, proposal_id, slug):
    """ Handler to display a detail page for a schedule item."""
    abort_if_invalid_year(year)

    #  We might want to look at performance here but I'm not sure it's a huge issue at the moment
    data = load_archive_file(year, "public", "schedule.json")
    for item in data:
        if item["id"] == proposal_id:
            break
    else:
        abort(404)

    correct_slug = proposal_slug(item["title"])
    if slug != correct_slug:
        return redirect(
            url_for(".item", year=year, proposal_id=proposal_id, slug=correct_slug)
        )

    return render_template(
        "schedule/historic/item.html", event=parse_event(item), year=year
    )


def talks_historic(year):
    abort_if_invalid_year(year)

    schedule = load_archive_file(year, "public", "schedule.json")
    event_data = load_archive_file(year, "event.json", raise_404=False)

    stage_events = []
    workshop_events = []

    for event in [parse_event(event) for event in schedule]:
        if event["source"] == "external":
            continue

        # Hack to remove Stitch's "hilarious" failed <script>
        if "<script>" in event.get("speaker", ""):
            event["speaker"] = event["speaker"][
                0 : event["speaker"].find("<script>")
            ]  # "Some idiot"

        # All official (non-external) content is on a stage or workshop, so we don't care about anything that isn't
        if event["type"] in ("talk", "performance"):
            events_list = stage_events
        elif event["type"] == "workshop":
            events_list = workshop_events
        else:
            continue

        # Make sure it's not already in the list (basically repeated workshops)
        if not any(e["title"] == event["title"] for e in events_list):
            events_list.append(event)

    def sort_key(event):
        # Sort should avoid leading punctuation and whitespace and be case-insensitive
        return event["title"].strip().strip("'").upper()

    stage_events.sort(key=sort_key)
    workshop_events.sort(key=sort_key)

    venues = [
        {"name": "Main Stages", "events": stage_events},
        {"name": "Workshops", "events": workshop_events},
    ]

    return render_template(
        "schedule/historic/talks.html", venues=venues, year=year, event=event_data
    )


def feed_historic(year, fmt):
    """ Serve a historic feed if it's available. """
    abort_if_invalid_year(year)
    file_path = archive_file(year, "public", f"schedule.{fmt}")
    return send_file(file_path)
