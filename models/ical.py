import requests
from icalendar import Calendar
import pytz

from main import db
from flask import current_app as app
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm.exc import NoResultFound

import re
from slugify import slugify_unicode


class CalendarSource(db.Model):
    __tablename__ = 'calendar_source'
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    name = db.Column(db.String)
    type = db.Column(db.String, default="Village")
    main_venue = db.Column(db.String)
    contact_phone = db.Column(db.String)
    contact_email = db.Column(db.String)
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)
    priority = db.Column(db.Integer, default=0)

    def __init__(self, url):
        self.url = url

    # Make sure these are identifiable to the memoize cache
    def __repr__(self):
        return "<%s %s: %s>" % (self.__class__.__name__, self.id, self.url)

    def refresh(self):
        request = requests.get(self.url.strip())

        cal = Calendar.from_ical(request.text)
        uid_seen = []

        if self.name is None:
            self.name = cal.get('X-WR-CALNAME')

        local_tz = pytz.timezone("Europe/London")
        for component in cal.walk():
            if component.name == 'VEVENT':
                if not component.get('uid'):
                    app.logger.debug('Ignoring event %s as it has no UID', component.get('Summary'))
                    continue

                uid = unicode(component['uid'])
                if uid in uid_seen:
                    app.logger.debug('Ignoring event %s with duplicate UID', component.get('Summary'))
                    continue

                uid_seen.append(uid)
                try:
                    event = CalendarEvent.query.filter_by(source_id=self.id, uid=uid).one()

                except NoResultFound:
                    event = CalendarEvent()
                    event.uid = uid
                    event.source_id = self.id
                    db.session.add(event)

                start_dt = component.get('dtstart').dt
                if start_dt.tzinfo is not None:
                    start_dt = start_dt.astimezone(local_tz).replace(tzinfo=None)
                event.start_dt = start_dt

                end_dt = component.get('dtend').dt
                if end_dt.tzinfo is not None:
                    end_dt = end_dt.astimezone(local_tz).replace(tzinfo=None)
                event.end_dt = end_dt

                event.summary = unicode(component.get('summary'))
                event.description = unicode(component.get('description'))
                event.location = unicode(component.get('location'))

                db.session.commit()

        events = CalendarEvent.query.filter_by(source_id=self.id)
        to_delete = [p for p in events if p.uid not in uid_seen]

        for e in to_delete:
            db.session.delete(e)
            db.session.commit()

    @classmethod
    def get_enabled_events(self):
        sources = CalendarSource.query.filter_by(enabled=True)
        events = []
        for source in sources:
            events.extend(source.events)
        return events

FavouriteCalendarEvents = db.Table('favourite_calendar_events',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('event_id', db.Integer, db.ForeignKey('calendar_event.id')),
)

class CalendarEvent(db.Model):
    __tablename__ = 'calendar_event'

    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String)
    start_dt = db.Column(db.DateTime(), nullable=False)
    end_dt = db.Column(db.DateTime(), nullable=False)

    source_id = db.Column(db.Integer, db.ForeignKey(CalendarSource.id),
                                      nullable=False, index=True)
    summary = db.Column(db.String, nullable=True)
    description = db.Column(db.String, nullable=True)
    location = db.Column(db.String, nullable=True)

    source = db.relationship(CalendarSource, backref='events')
    calendar_favourites = db.relationship('User', secondary=FavouriteCalendarEvents, backref=db.backref('calendar_favourites', lazy='dynamic'))

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
            words = re.split(' +|[,.;:!?]+', self.summary)
            break_words = ['and', 'which', 'with', 'without', 'for', '-', '']

            for i, word in reversed(list(enumerate(words))):
                new_slug = slugify_unicode(' '.join(words[:i])).lower()
                if word in break_words:
                    if len(new_slug) > 10 and not len(new_slug) > 60:
                        slug = new_slug
                        break

                elif len(slug) > 60 and len(new_slug) > 10:
                    slug = new_slug

        if len(slug) > 60:
            slug = slug[:60] + '-'

        return slug

    __table_args__ = (
        UniqueConstraint(source_id, uid),
    )

