""" Schedule CLI tasks """
import json
from collections import OrderedDict

from flask import current_app as app

from main import db
from models.ical import CalendarSource
from models.cfp import Venue
from models.village import Village

from . import schedule


@schedule.cli.command("create_calendars")
def create_calendars(self):
    icals = json.load(open("calendars.json"))

    for cal in icals:
        existing_calendar = CalendarSource.query.filter_by(url=cal["url"]).first()
        if existing_calendar:
            source = existing_calendar
            app.logger.info("Refreshing calendar %s", source.name)
        else:
            source = CalendarSource(cal["url"])
            app.logger.info("Adding calendar %s", cal["name"])

        cal["lat"] = cal.get("lat")
        cal["lon"] = cal.get("lon")

        for f in ["name", "type", "priority", "main_venue", "lat", "lon"]:
            cur_val = getattr(source, f)
            new_val = cal[f]

            if cur_val != new_val:
                app.logger.info(" %10s: %r -> %r", f, cur_val, new_val)
                setattr(source, f, new_val)

        db.session.add(source)

    db.session.commit()


@schedule.cli.command("refresh_calendars")
def refresh_calendars(self):
    for source in CalendarSource.query.filter_by(enabled=True).all():
        source.refresh()

    db.session.commit()


@schedule.cli.command("export_calendars")
def export_calendars(self):
    data = []
    calendars = CalendarSource.query.filter_by(enabled=True).order_by(
        CalendarSource.priority, CalendarSource.id
    )
    for source in calendars:
        source_data = OrderedDict(
            [
                ("name", source.name),
                ("url", source.url),
                ("type", source.type),
                ("priority", source.priority),
                ("main_venue", source.main_venue),
            ]
        )
        if source.lat:
            source_data["lat"] = source.lat
            source_data["lon"] = source.lon

        data.append(source_data)

    json.dump(data, open("calendars.json", "w"), indent=4, separators=(",", ": "))


def create_venue_if_not_existing(venue):
    existing_venue = Venue.query.filter_by(name=venue.name).first()
    if not existing_venue:
        app.logger.info("Adding new venue {}".format(venue.name))
        db.session.add(venue)
        db.session.commit()
    else:
        app.logger.info("Venue already exists for {}".format(venue.name))


@schedule.cli.command("create_venues")
def create_venues():
    core_venues = ["Main Bar", "Lounge"]
    for venue in core_venues:
        create_venue_if_not_existing(Venue(name=venue, scheduled_content_only=False))

    for village in Village.query.all():
        venue = Venue(
            name=village.name, village_id=village.id, scheduled_content_only=False
        )
        create_venue_if_not_existing(venue)
