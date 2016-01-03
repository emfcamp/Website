from main import db, cache

class FeatureFlag(db.Model):
    __tablename__ = 'feature_flags'
    name = db.Column(db.String, primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False)

    def __init__(self, name, enabled=False):
        self.name = name
        self.enabled = enabled

    @classmethod
    @cache.memoize(timeout=30)
    def get_flag(self, name):
        return FeatureFlag.query.get(name)
