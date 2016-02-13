from main import db
from datetime import datetime

# state: [allowed next state, ] pairs
CFP_STATES = { 'edit': ['new'],
               'new': ['locked'],
               'locked': ['checked', 'rejected', 'edit'],
               'checked': ['anonymised', 'edit'],
               'rejected': ['edit'],
               'anonymised': ['reviewed', 'edit'],
               'reviewed': ['accepted', 'edit'],
               'accepted': ['finished'],
               'finished': [] }

class CfpStateException(Exception):
    pass


class Proposal(db.Model):
    __versioned__ = {}
    __tablename__ = 'proposal'
    # Admin
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    modified = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    state = db.Column(db.String, nullable=False, default='new')
    type = db.Column(db.String, nullable=False)  # talk, workshop or installation

    # Core information
    title = db.Column(db.String, nullable=False)
    description = db.Column(db.String, nullable=False)
    requirements = db.Column(db.String)
    length = db.Column(db.String)  # only used for talks and workshops
    notice_required = db.Column(db.String)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)

    # Flags
    needs_help = db.Column(db.Boolean)
    needs_money = db.Column(db.Boolean)
    one_day = db.Column(db.Boolean)

    __mapper_args__ = {'polymorphic_on': type}

    def set_state(self, state):
        state = state.lower()
        if state not in CFP_STATES:
            raise CfpStateException('"%s" is not a valid state' % state)

        if state not in CFP_STATES[self.state]:
            raise CfpStateException('"%s->%s" is not a valid transition' % (self.state, state))

        self.state = state


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


class ProposalCategory(db.Model):
    __tablename__ = 'category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    proposals = db.relationship(TalkProposal, backref='category')


class CFPMessage(db.Model):
    __tablename__ = 'message'
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    proposal_id = db.Column(db.Integer, db.ForeignKey('proposal.id'), nullable=False)
    message = db.Column(db.String, nullable=False)

