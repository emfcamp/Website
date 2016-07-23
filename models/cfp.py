from main import db
from datetime import datetime
from collections import namedtuple
from dateutil.parser import parse as parse_date
from sqlalchemy import UniqueConstraint

# state: [allowed next state, ] pairs
CFP_STATES = { 'edit': ['accepted', 'rejected', 'new'],
               'new': ['accepted', 'rejected', 'locked'],
               'locked': ['accepted', 'rejected', 'checked', 'edit'],
               'checked': ['accepted', 'rejected', 'anonymised', 'anon-blocked', 'edit'],
               'rejected': ['accepted', 'rejected', 'edit'],
               'cancelled': ['accepted', 'rejected', 'edit'],
               'anonymised': ['accepted', 'rejected', 'reviewed', 'edit'],
               'anon-blocked': ['accepted', 'rejected', 'reviewed', 'edit'],
               'reviewed': ['accepted', 'rejected', 'edit'],
               'manual-review': ['accepted', 'rejected', 'edit'],
               'accepted': ['accepted', 'rejected', 'finished'],
               'finished': ['rejected', 'finished'] }

# Most of these states are the same they're kept distinct for semantic reasons
# and because I'm lazy
VOTE_STATES = {'new': ['voted', 'recused', 'blocked'],
               'voted': ['resolved', 'stale'],
               'recused': ['resolved', 'stale'],
               'blocked': ['resolved', 'stale'],
               'resolved': ['voted', 'recused', 'blocked'],
               'stale': ['voted', 'recused', 'blocked'],
               }

# These are the time periods speakers can select as being available in the form
# Oh no there's vomit everywhere
TIME_PERIODS = {}
_month = (2016, 8) # Lol rite # FIXME
_periods = {
    5: ['fri_13_16', 'fri_16_20'],
    6: ['sat_10_13', 'sat_13_16', 'sat_16_20'],
    7: ['sun_10_13', 'sun_13_16', 'sun_16_20'],
}

period = namedtuple('Period', 'start end')
for day, times in _periods.items():
    for time_str in times:
        _, start_hr, end_hr = time_str.split('_')
        TIME_PERIODS[time_str] = period(
            datetime(_month[0], _month[1], int(day), int(start_hr)),
            datetime(_month[0], _month[1], int(day), int(end_hr))
        )

# Override the friday start time to begin at 2pm, the only talk at 1pm
# should be the opening ceremony
TIME_PERIODS['fri_13_16'] = period(
    datetime(_month[0], _month[1], 5, 14),
    datetime(_month[0], _month[1], 5, 16)
)

# We may also have other venues in the DB, but these are the ones to be
# returned by default if there are none
DEFAULT_VENUES = {
    'talk': ['Stage A', 'Stage B', 'Stage C'],
    'workshop': ['Workshop 1', 'Workshop 2'],
    'performance': ['Stage A'],
    'installation': []
}

class CfpStateException(Exception):
    pass

class InvalidVenueException(Exception):
    pass


FavouriteProposals = db.Table('favourite_proposals',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('proposal_id', db.Integer, db.ForeignKey('proposal.id')),
)

class Proposal(db.Model):
    __versioned__ = {}
    __tablename__ = 'proposal'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    anonymiser_id = db.Column(db.Integer, db.ForeignKey('user.id'), default=None)
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow)
    state = db.Column(db.String, nullable=False, default='new')
    type = db.Column(db.String, nullable=False)  # talk, workshop or installation

    # Core information
    title = db.Column(db.String, nullable=False)
    description = db.Column(db.String, nullable=False)
    requirements = db.Column(db.String)
    length = db.Column(db.String)  # only used for talks and workshops
    notice_required = db.Column(db.String)

    # Flags
    needs_help = db.Column(db.Boolean, nullable=False, default=False)
    needs_money = db.Column(db.Boolean, nullable=False, default=False)
    one_day = db.Column(db.Boolean, nullable=False, default=False)
    has_rejected_email = db.Column(db.Boolean, nullable=False, default=False)

    # References to this table
    messages = db.relationship('CFPMessage', backref='proposal')
    votes = db.relationship('CFPVote', backref='proposal')
    favourites = db.relationship('User', secondary=FavouriteProposals, backref=db.backref('favourites', lazy='dynamic'))

    # Fields for finalised info
    published_names = db.Column(db.String)
    arrival_period = db.Column(db.String)
    departure_period = db.Column(db.String)
    telephone_number = db.Column(db.String)
    may_record = db.Column(db.Boolean)
    needs_laptop = db.Column(db.Boolean)
    available_times = db.Column(db.String)

    # Fields for scheduling
    allowed_venues = db.Column(db.String, nullable=True)
    allowed_times = db.Column(db.String, nullable=True)
    scheduled_duration = db.Column(db.Integer, nullable=True)
    scheduled_time = db.Column(db.DateTime, nullable=True)
    scheduled_venue = db.Column(db.Integer, db.ForeignKey('venue.id'))
    potential_time = db.Column(db.DateTime, nullable=True)
    potential_venue = db.Column(db.Integer, db.ForeignKey('venue.id'))

    __mapper_args__ = {'polymorphic_on': type}

    def get_user_vote(self, user):
        # there can't be more than one vote per user per proposal
        return CFPVote.query.filter_by(proposal_id=self.id, user_id=user.id)\
            .first()

    def set_state(self, state):
        state = state.lower()
        if state not in CFP_STATES:
            raise CfpStateException('"%s" is not a valid state' % state)

        if state not in CFP_STATES[self.state]:
            raise CfpStateException('"%s->%s" is not a valid transition' % (self.state, state))

        self.state = state

    def get_unread_vote_note_count(self):
        return len([v for v in self.votes if not v.has_been_read])

    def get_total_note_count(self):
        return len([v for v in self.votes if v.note and len(v.note) > 0])

    def get_unread_messages(self, user):
        return [m for m in self.messages if (not m.has_been_read and
                                             m.is_user_recipient(user))]

    def get_unread_count(self, user):
        return len(self.get_unread_messages(user))

    def mark_messages_read(self, user):
        messages = self.get_unread_messages(user)
        for msg in messages:
            msg.has_been_read = True
        db.session.commit()
        return len(messages)

    def get_allowed_venues(self):
        venue_names = DEFAULT_VENUES[self.type]
        if self.allowed_venues:
            venue_names = [ v.strip() for v in self.allowed_venues.split(',') ]
        found = Venue.query.filter(Venue.name.in_(venue_names)).all()
        # If we didn't actually find all the venues we're using, bail hard
        if len(found) != len(venue_names):
            raise InvalidVenueException("Invalid Venue in allowed_venues!")
        return found

    def get_allowed_venues_serialised(self):
        return ','.join([ v.name for v in self.get_allowed_venues() ])

    # Reduces the time periods to the smallest contiguous set we can
    def make_periods_contiguous(self, time_periods):
        time_periods.sort(key=lambda x: x.start)
        contiguous_periods = [time_periods.pop(0)]
        for time_period in time_periods:
            if time_period.start <= contiguous_periods[-1].end and\
                    contiguous_periods[-1].end < time_period.end:
                contiguous_periods[-1] = period(contiguous_periods[-1].start, time_period.end)
                continue

            contiguous_periods.append(time_period)
        return contiguous_periods

    def get_allowed_time_periods(self):
        time_periods = []

        if self.allowed_times:
            for p in self.allowed_times.split('\n'):
                if p:
                    start, end = p.split(' > ')
                    time_periods.append(
                        period(
                            parse_date(start),
                            parse_date(end),
                        )
                    )

        # If we've not overridden it, use the user-specified periods
        if not time_periods and self.available_times:
            for p in self.available_times.split(','):
                if p:
                    time_periods.append(TIME_PERIODS[p.strip()])
        return self.make_periods_contiguous(time_periods)

    def get_allowed_time_periods_serialised(self):
        return '\n'.join([ "%s > %s" % (v.start, v.end) for v in self.get_allowed_time_periods() ])

    def get_allowed_time_periods_with_default(self):
        allowed_time_periods = self.get_allowed_time_periods()
        if not allowed_time_periods:
            allowed_time_periods = TIME_PERIODS.values()
        return self.make_periods_contiguous(allowed_time_periods)

class PerformanceProposal(Proposal):
    __mapper_args__ = {'polymorphic_identity': 'performance'}


class TalkProposal(Proposal):
    __mapper_args__ = {'polymorphic_identity': 'talk'}


class WorkshopProposal(Proposal):
    __mapper_args__ = {'polymorphic_identity': 'workshop'}
    attendees = db.Column(db.String)
    cost = db.Column(db.String)


class InstallationProposal(Proposal):
    __mapper_args__ = {'polymorphic_identity': 'installation'}
    size = db.Column(db.String)
    funds = db.Column(db.String, nullable=True)


class CFPMessage(db.Model):
    __tablename__ = 'cfp_message'
    id = db.Column(db.Integer, primary_key=True)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposal.id'), nullable=False)

    message = db.Column(db.String, nullable=False)
    # Flags
    is_to_admin = db.Column(db.Boolean)
    has_been_read = db.Column(db.Boolean, default=False)

    def is_user_recipient(self, user):
        """
        Because we want messages from proposers to be visible to all admin
        we need to infer the 'to' portion of the email, either it is
        to the proposer (from admin) or to admin (& from the proposer).

        Obviously if the proposer is also an admin this doesn't really work
        but equally they should know where to ask.
        """
        is_user_admin = user.has_permission('admin')
        is_user_proposer = user.id == self.proposal.user_id

        if is_user_proposer and not self.is_to_admin:
            return True

        if is_user_admin and self.is_to_admin:
            return True

        return False

class CFPVote(db.Model):
    __versioned__ = {}
    __tablename__ = 'cfp_vote'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposal.id'), nullable=False)
    state = db.Column(db.String, nullable=False)
    has_been_read = db.Column(db.Boolean, nullable=False, default=False)

    created = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    modified = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    vote = db.Column(db.Integer) # Vote can be null for abstentions
    note = db.Column(db.String)

    def __init__(self, user, proposal):
        self.user = user
        self.proposal = proposal
        self.state = 'new'

    def set_state(self, state):
        state = state.lower()
        if state not in VOTE_STATES:
            raise CfpStateException('"%s" is not a valid state' % state)

        if state not in VOTE_STATES[self.state]:
            raise CfpStateException('"%s->%s" is not a valid transition' % (self.state, state))

        self.state = state

class Venue(db.Model):
    __tablename__ = 'venue'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    type = db.Column(db.String, nullable=True)
    __table_args__ = (
        UniqueConstraint('name', name='_venue_name_uniq'),
    )

# TODO: change the relationships on User and Proposal to 1-to-1
db.Index('ix_cfp_vote_user_id_proposal_id', CFPVote.user_id, CFPVote.proposal_id, unique=True)
