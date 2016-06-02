from main import db
from datetime import datetime

# state: [allowed next state, ] pairs
CFP_STATES = { 'edit': ['accepted', 'rejected', 'new'],
               'new': ['accepted', 'rejected', 'locked'],
               'locked': ['accepted', 'rejected', 'checked', 'edit'],
               'checked': ['accepted', 'rejected', 'anonymised', 'anon-blocked', 'edit'],
               'rejected': ['accepted', 'rejected', 'edit'],
               'anonymised': ['accepted', 'rejected', 'reviewed', 'edit'],
               'anon-blocked': ['accepted', 'rejected', 'reviewed', 'edit'],
               'reviewed': ['accepted', 'rejected', 'edit'],
               'manual-review': ['accepted', 'rejected', 'edit'],
               'accepted': ['accepted', 'rejected', 'finished'],
               'finished': ['accepted', 'rejected'] }

# Most of these states are the same they're kept distinct for semantic reasons
# and because I'm lazy
VOTE_STATES = {'new': ['voted', 'recused', 'blocked'],
               'voted': ['resolved', 'stale'],
               'recused': ['resolved', 'stale'],
               'blocked': ['resolved', 'stale'],
               'resolved': ['voted', 'recused', 'blocked'],
               'stale': ['voted', 'recused', 'blocked'],
               }

class CfpStateException(Exception):
    pass


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

# TODO: change the relationships on User and Proposal to 1-to-1
db.Index('ix_cfp_vote_user_id_proposal_id', CFPVote.user_id, CFPVote.proposal_id, unique=True)

