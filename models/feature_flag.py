from main import db

# feature flags that can be overridden in the DB
DB_FEATURE_FLAGS = [
    'TICKET_SALES',
    'BANK_TRANSFER',
    'BANK_TRANSFER_EURO',
    'GOCARDLESS',
    'GOCARDLESS_EURO',
    'STRIPE',
    'CFP',
    'VOLUNTEERS',
    'RADIO',
    'ISSUE_TICKETS',
]

class FeatureFlag(db.Model):
    __tablename__ = 'feature_flag'
    feature = db.Column(db.String, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False)

    def __init__(self, feature, enabled=False):
        self.feature = feature
        self.enabled = enabled

