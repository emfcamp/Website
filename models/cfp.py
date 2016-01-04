from main import db, cache
from datetime import datetime


class Proposal(db.Model):
    __tablename__ = 'proposal'
    # Admin
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow)
    state = db.Column(db.String, nullable=False, default='new')
    type = db.Column(db.String, nullable=False) # Talk, workshop or installation

    # Core information
    title = db.Column(db.String, nullable=False)
    description = db.Column(db.String)
    requirements = db.Column(db.String)
    length = db.Column(db.String)

    # Flags
    requires_help = db.Column(db.Boolean)
    requires_notice = db.Column(db.String)
    requires_financing = db.Column(db.Boolean)
    one_day = db.Column(db.Boolean)

    # Store the next version so we can find the most recent by looking for NULL
    next_version_id = db.Column(db.Integer, db.ForeignKey('proposal.id'))
    previous_version = db.relationship('Proposal')

    __mapper_args__ = {'polymorphic_on': type}


class TalkProposal(Proposal):
    __mapper_args__ = {'polymorphic_identity': 'talk'}
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    category = db.relationship('TalkCategory', backref='proposals')


class WorkshopProposal(Proposal):
    __mapper_args__ = {'polymorphic_identity': 'workshop'}
    attendees = db.Column(db.String)
    cost = db.Column(db.Integer)


class InstallationProposal(Proposal):
    __mapper_args__ = {'polymorphic_identity': 'installation'}
    size = db.Column(db.String)


class TalkCategory(db.Model):
    __tablename__ = 'category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)

    @classmethod
    @cache.cached(timeout=60, key_prefix='get_cfp_categories')
    def get_categories_selection(cls):
        categories = TalkCategory.query.all()

        # Id has to be a string to match the HTML return
        categories = [(str(c.id), c.name) for c in categories]
        categories.append(('NULL', 'None of the above'))

        return categories
