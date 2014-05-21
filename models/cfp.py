from main import db


class Proposal(db.Model):
    __tablename__ = 'proposal'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, nullable=False)
    name = db.Column(db.String)
    title = db.Column(db.String)
    description = db.Column(db.String)
    length = db.Column(db.String)
