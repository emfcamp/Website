from main import db

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
