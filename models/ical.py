import requests
from icalendar import Calendar
from pytz import timezone

from main import db

local_zone = timezone('Europe/London')

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

    def get_ical_feed(self):
        request = requests.get(self.url)
        if request.status_code != 200:
            return self.proposals

        cal = Calendar.from_ical(request.text)
        uid_seen = []
        for component in cal.walk():
            if component.name == 'VEVENT':
                uid = unicode(component.get('uid'))
                uid_seen.append(uid)
                proposal = ICalProposal.query.get(uid)

                if proposal is None:
                    proposal = ICalProposal()
                    proposal.uid = uid
                    proposal.venue_id = self.id
                    db.session.add(proposal)

                proposal.start_date = component.get('dtstart').dt
                proposal.start_date.replace(tzinfo=local_zone)
                proposal.end_date = component.get('dtend').dt
                proposal.end_date.replace(tzinfo=local_zone)

                proposal.title = unicode(component.get('summary'))
                proposal.description = unicode(component.get('description'))

                db.session.commit()

        proposals = ICalProposal.query.filter_by(venue_id=self.id)
        to_delete = [p for p in proposals if p.uid not in uid_seen]

        for uid in to_delete:
            db.session.delete(ICalProposal.query.get(uid))
            db.session.commit()

        return self.proposals


class ICalProposal(db.Model):
    __tablename__ = 'ical_proposal'

    id = db.Column(db.Integer)
    uid = db.Column(db.String, primary_key=True)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    venue_id = db.Column(db.Integer, db.ForeignKey('ical_source.id'),
                         nullable=False, index=True)
    title = db.Column(db.String, nullable=True)
    description = db.Column(db.String, nullable=True)

    venue = db.relationship('ICalSource', backref='proposals')

