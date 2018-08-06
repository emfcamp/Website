from main import db, cache

# feature flags that can be overridden in the DB
DB_FEATURE_FLAGS = [
    'BANK_TRANSFER',
    'BANK_TRANSFER_EURO',
    'CFP',
    'CFP_FINALISE',
    'GOCARDLESS',
    'GOCARDLESS_EURO',
    'ISSUE_TICKETS',
    'RADIO',
    'SCHEDULE',
    'STRIPE',
    'TICKET_SALES',
]

class FeatureFlag(db.Model):
    __tablename__ = 'feature_flag'
    __export_data__ = False
    feature = db.Column(db.String, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False)

    def __init__(self, feature, enabled=False):
        self.feature = feature
        self.enabled = enabled

@cache.cached(timeout=60, key_prefix='get_db_flags')
def get_db_flags():
    flags = FeatureFlag.query.all()
    flags = {f.feature: f.enabled for f in flags}

    return flags

def refresh_flags():
    key = get_db_flags.make_cache_key()
    cache.delete(key)

