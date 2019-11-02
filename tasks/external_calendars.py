import json
from collections import OrderedDict

from flask import current_app as app
from flask_script import Command

from main import db
from models.ical import CalendarSource


class CreateCalendars(Command):
    def run(self):
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


class RefreshCalendars(Command):
    def run(self):
        for source in CalendarSource.query.filter_by(enabled=True).all():
            source.refresh()

        db.session.commit()


class ExportCalendars(Command):
    def run(self):
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
