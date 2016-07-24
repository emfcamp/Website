import requests
from icalendar import Calendar

from main import db, cache

class ICalSource(db.Model):
    __tablename__ = 'ical_source'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    venue = db.Column(db.String, nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    url = db.Column(db.String, nullable=False)
    contact_phone = db.Column(db.String)
    contact_email = db.Column(db.String)
    lat = db.Column(db.Float)
    lon = db.Column(db.Float)

    # Make sure these are identifiable to the memoize cache
    def __repr__(self):
        return "%s(%s: '%s')" % (self.__class__.__name__, self.id, self.url)

    @cache.memoize(timeout=300)
    def get_ical_feed(self):
        request = requests.get(self.url)
        if request.status_code != 200:
            return []

        cal = Calendar.from_ical(request.text)
        res = []
        for component in cal.walk():
            if component.name == 'VEVENT':
                event = {
                    'start_date': component.get('dtstart').dt,
                    'end_date': component.get('dtend').dt,
                    'title': component.get('summary').decode(),
                    'description': component.get('description').decode(),
                    'venue': self.venue,
                    'id': component.get('uid').decode(),
                }

                res.append(event)

        return res
