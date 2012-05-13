from main import db

class TicketType(db.Model):
    __tablename__ = 'ticket_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    cost = db.Column(db.Numeric, nullable=False)

class Ticket(db.Model):
    __tablename__ = 'ticket'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship("User", backref="tickets")
    type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False)
    type = db.relationship("TicketType")
    state = db.Enum('unpaid', 'paid', nullable=False)
