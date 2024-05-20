from models import BaseModel
from main import db


class Card(BaseModel):
    __tablename__ = "volunteer_card"
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String, nullable=False, default="volunteer")
    state = db.Column(db.String, nullable=False, default="queued")
    printer = db.Column(db.String, nullable=False, default="volunteer")
    volunteer_number = db.Column(db.String, nullable=False)
    name = db.Column(db.String, nullable=False)
    alias = db.Column(db.String, nullable=True)
    pronouns = db.Column(db.String, nullable=False)
    line_one = db.Column(db.String, nullable=False)
    line_two = db.Column(db.String, nullable=False)
