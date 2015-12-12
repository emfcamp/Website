from main import db


class Proposal(db.Model):
    __tablename__ = 'proposal'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String, nullable=False)
    description = db.Column(db.String)
    length = db.Column(db.String)
    need_finance = db.Column(db.Boolean)
    one_day = db.Column(db.Boolean)
    type = db.Column(db.String, nullable=False)
    diversity = db.relationship('ProposalDiversity', uselist=False, backref='cfp')
    __mapper_args__ = {'polymorphic_on': type}

class TalkProposal(Proposal):
    __mapper_args__ = {'polymorphic_identity': 'talk'}
    experience = db.Column(db.String)

class WorkshopProposal(Proposal):
    __mapper_args__ = {'polymorphic_identity': 'workshop'}
    attendees = db.Column(db.String)

class InstallationProposal(Proposal):
    __mapper_args__ = {'polymorphic_identity': 'installation'}
    size = db.Column(db.String)

class ProposalDiversity(db.Model):
    __tablename__ = 'diversity'
    cfp_id = db.Column(db.Integer, db.ForeignKey('proposal.id'), nullable=False, primary_key=True)
    age = db.Column(db.String)
    gender = db.Column(db.String)
    ethnicity = db.Column(db.String)


