""" View helpers for displaying historic schedules.

    These are served from static files in this repository as the database is wiped every year.
"""
from flask import render_template, abort, redirect, url_for

from models.cfp import proposal_slug
from ..common import load_archive_file


def item_historic(year, proposal_id, slug):
    """ Handler to display a detail page for a schedule item."""
    if year < 2012:
        abort(404)

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

    return render_template("schedule/historic/item.html", proposal=item, year=year)


def talks_historic(year):
    if year < 2012:
        abort(404)
    data = load_archive_file(year, "public", "schedule.json")

    stage_events = []
    workshop_events = []

    for event in data:
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

    # Sort should avoid leading punctuation and whitespace and be case-insensitive
    stage_events.sort(key=lambda event: event["title"].strip().strip("'").upper())
    workshop_events.sort(key=lambda event: event["title"].strip().strip("'").upper())

    venues = [
        {"name": "Main Stages", "events": stage_events},
        {"name": "Workshops", "events": workshop_events},
    ]

    return render_template("schedule/historic/talks.html", venues=venues, year=year)
