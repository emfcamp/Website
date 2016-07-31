import requests
from icalendar import Calendar
import pytz

from main import db
from flask import current_app as app
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm.exc import NoResultFound


class CalendarSource(db.Model):
    __tablename__ = 'calendar_source'
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    name = db.Column(db.String)
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
        request = requests.get(self.url)

        cal = Calendar.from_ical(request.text)
        uid_seen = []

        if self.name is None:
            self.name = cal.get('X-WR-CALNAME')

        # Fall back to event-local time
        default_tz = cal.get('X-WR-TIMEZONE', 'Europe/London')

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
                if start_dt.tzinfo is None:
                    start_dt = default_tz.localize(start_dt)
                event.start_dt = start_dt

                end_dt = component.get('dtend').dt
                if end_dt.tzinfo is None:
                    end_dt = default_tz.localize(end_dt)
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


class CalendarEvent(db.Model):
    __tablename__ = 'calendar_event'

    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String)
    # iCal supports some weird timezones, so let's see if this will do
    # You can use UTC for maths even if we've lost the information
    start_utc = db.Column(db.DateTime(), nullable=False)
    start_local = db.Column(db.DateTime(), nullable=False)
    start_tz = db.Column(db.String)
    end_utc = db.Column(db.DateTime(), nullable=False)
    end_local = db.Column(db.DateTime(), nullable=False)
    end_tz = db.Column(db.String)

    source_id = db.Column(db.Integer, db.ForeignKey(CalendarSource.id),
                                      nullable=False, index=True)
    summary = db.Column(db.String, nullable=True)
    description = db.Column(db.String, nullable=True)
    location = db.Column(db.String, nullable=True)

    source = db.relationship(CalendarSource, backref='events')

    @property
    def start_dt(self):
        return pytz.timezone(self.start_tz).localize(self.start_local)

    @start_dt.setter
    def start_dt(self, dt):
        self.start_utc = dt.astimezone(pytz.UTC).replace(tzinfo=None)
        self.start_local = dt.replace(tzinfo=None)
        self.start_tz = dt.tzinfo.zone

    @property
    def end_dt(self):
        return pytz.timezone(self.end_tz).localize(self.end_local)

    @end_dt.setter
    def end_dt(self, dt):
        self.end_utc = dt.astimezone(pytz.UTC).replace(tzinfo=None)
        self.end_local = dt.replace(tzinfo=None)
        self.end_tz = dt.tzinfo.zone

    __table_args__ = (
        UniqueConstraint(source_id, uid),
    )

