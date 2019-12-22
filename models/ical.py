import requests
import re

from geoalchemy2.shape import to_shape
from icalendar import Calendar
import pendulum
from shapely.geometry import Point
from slugify import slugify_unicode
from sqlalchemy import UniqueConstraint, func, select
from sqlalchemy.orm import column_property
from sqlalchemy.orm.exc import NoResultFound

from main import db
from models import event_start, event_end


class CalendarSource(db.Model):
    __tablename__ = "calendar_source"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    url = db.Column(db.String, nullable=False)
    name = db.Column(db.String)
    type = db.Column(db.String, default="Village")
    priority = db.Column(db.Integer, default=0)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    refreshed_at = db.Column(db.DateTime())

    displayed = db.Column(db.Boolean, nullable=False, default=False)
    published = db.Column(db.Boolean, nullable=False, default=False)
    main_venue = db.Column(db.String)
    map_obj_id = db.Column(db.Integer, db.ForeignKey("map_object.id"))
    contact_phone = db.Column(db.String)
    contact_email = db.Column(db.String)

    user = db.relationship("User", backref="calendar_sources")
    mapobj = db.relationship("MapObject")

    # Make sure these are identifiable to the memoize cache
    def __repr__(self):
        return "<%s %s: %s>" % (self.__class__.__name__, self.id, self.url)

    @classmethod
    def get_export_data(cls):
        sources = cls.query.with_entities(
            cls.id,
            cls.name,
            cls.type,
            cls.enabled,
            cls.url,
            cls.main_venue,
            cls.priority,
            cls.map_obj_id,
        ).order_by(cls.id)

        data = {"public": {"sources": sources}, "tables": ["calendar_source"]}

        return data

    def refresh(self):
        request = requests.get(self.url)

        cal = Calendar.from_ical(request.text)
        if self.name is None:
            self.name = cal.get("X-WR-CALNAME")

        for event in self.events:
            event.displayed = False

        local_tz = pendulum.timezone("Europe/London")
        alerts = []
        uids_seen = set()
        out_of_range_event = False
        for component in cal.walk():
            if component.name == "VEVENT":
                summary = component.get("Summary")

                # postgres converts to UTC if given an aware datetime, so strip it up front
                start_dt = pendulum.instance(component.get("dtstart").dt)
                start_dt = local_tz.convert(start_dt).naive()

                end_dt = pendulum.instance(component.get("dtend").dt)
                end_dt = local_tz.convert(end_dt).naive()

                name = summary
                if summary and start_dt:
                    name = "'{}' at {}".format(summary, start_dt)
                elif summary:
                    name = "'{}'".format(summary)
                elif start_dt:
                    name = "Event at {}".format(start_dt)
                else:
                    name = len(self.events) + 1

                if not component.get("uid"):
                    alerts.append(("danger", "{} has no UID".format(name)))
                    continue

                uid = str(component["uid"])
                if uid in uids_seen:
                    alerts.append(
                        ("danger", "{} has duplicate UID {}".format(name, uid))
                    )
                    continue
                uids_seen.add(uid)

                if "rrule" in component:
                    alerts.append(
                        ("warning", "{} has rrule, which is not processed".format(uid))
                    )

                # Allow a bit of slop for build-up events
                if (
                    start_dt < event_start() - pendulum.duration(days=2)
                    and not out_of_range_event
                ):
                    alerts.append(
                        (
                            "warning",
                            "At least one event ({}) is before the start of the event".format(
                                uid
                            ),
                        )
                    )
                    out_of_range_event = True

                if (
                    end_dt > event_end() + pendulum.duration(days=1)
                    and not out_of_range_event
                ):
                    alerts.append(
                        (
                            "warning",
                            "At least one event ({}) is after the end of the event".format(
                                uid
                            ),
                        )
                    )
                    out_of_range_event = True

                if start_dt > end_dt:
                    alerts.append(
                        (
                            "danger",
                            "Start time for {} is after its end time".format(uid),
                        )
                    )
                    out_of_range_event = True

                try:
                    event = CalendarEvent.query.filter_by(
                        source_id=self.id, uid=uid
                    ).one()

                except NoResultFound:
                    event = CalendarEvent(uid=uid)
                    self.events.append(event)
                    if len(self.events) > 1000:
                        raise Exception("Too many events in feed")

                event.start_dt = start_dt
                event.end_dt = end_dt
                event.summary = component.get("summary")
                event.description = component.get("description")
                event.location = component.get("location")
                event.displayed = True

        self.refreshed_at = pendulum.now()

        return alerts

    @property
    def latlon(self):
        if self.mapobj:
            obj = to_shape(self.mapobj.geom)
            if isinstance(obj, Point):
                return (obj.y, obj.x)
        return None

    @classmethod
    def get_enabled_events(self):
        sources = CalendarSource.query.filter_by(published=True, displayed=True)
        events = []
        for source in sources:
            events.extend(source.events)
        return events


FavouriteCalendarEvent = db.Table(
    "favourite_calendar_event",
    db.Model.metadata,
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column(
        "event_id", db.Integer, db.ForeignKey("calendar_event.id"), primary_key=True
    ),
)


class CalendarEvent(db.Model):
    __tablename__ = "calendar_event"

    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String)
    start_dt = db.Column(db.DateTime(), nullable=False)
    end_dt = db.Column(db.DateTime(), nullable=False)
    displayed = db.Column(db.Boolean, nullable=False, default=True)

    source_id = db.Column(
        db.Integer, db.ForeignKey(CalendarSource.id), nullable=False, index=True
    )
    summary = db.Column(db.String, nullable=True)
    description = db.Column(db.String, nullable=True)
    location = db.Column(db.String, nullable=True)

    source = db.relationship(CalendarSource, backref="events")
    calendar_favourites = db.relationship(
        "User", secondary=FavouriteCalendarEvent, backref="calendar_favourites"
    )

    favourite_count = column_property(
        select([func.count(FavouriteCalendarEvent.c.user_id)]).where(
            FavouriteCalendarEvent.c.user_id == id
        ),
        deferred=True,
    )

    @classmethod
    def get_export_data(cls):
        events = cls.query.with_entities(
            cls.source_id,
            cls.uid,
            cls.start_dt,
            cls.end_dt,
            cls.summary,
            cls.description,
            cls.location,
            cls.favourite_count,
        ).order_by(cls.source_id, cls.id)

        data = {
            "public": {"events": events},
            "tables": ["calendar_event", "favourite_calendar_event"],
        }

        return data

    @property
    def title(self):
        return self.summary

    @property
    def venue(self):
        if self.source.main_venue:
            return self.source.main_venue
        else:
            return self.location

    @property
    def type(self):
        return self.source.type

    @property
    def slug(self):
        slug = slugify_unicode(self.summary).lower()
        if len(slug) > 60:
            words = re.split(" +|[,.;:!?]+", self.summary)
            break_words = ["and", "which", "with", "without", "for", "-", ""]

            for i, word in reversed(list(enumerate(words))):
                new_slug = slugify_unicode(" ".join(words[:i])).lower()
                if word in break_words:
                    if len(new_slug) > 10 and not len(new_slug) > 60:
                        slug = new_slug
                        break

                elif len(slug) > 60 and len(new_slug) > 10:
                    slug = new_slug

        if len(slug) > 60:
            slug = slug[:60] + "-"

        return slug

    @property
    def latlon(self):
        if self.source.latlon:
            return self.source.latlon
        return None

    @property
    def map_link(self):
        latlon = self.latlon
        if latlon:
            return "https://map.emfcamp.org/#20/%s/%s" % (latlon[0], latlon[1])
        return None

    __table_args__ = (UniqueConstraint(source_id, uid),)
