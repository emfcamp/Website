from main import db

class TicketType(db.Model):
    __tablename__ = 'ticket_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)


class Ticket(db.Model):
    __tablename__ = 'ticket_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    type = relationship("TicketType")
    capacity = db.Column(db.Integer, nullable=False)
