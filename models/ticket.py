from main import db

class TicketType(db.Model):
    __tablename__ = 'ticket_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    cost = db.Column(db.Numeric, nullable=False)

    def __init__(name, capacity, cost):
        self.name = name
        self.capacity = capacity
        self.cost = cost

class Ticket(db.Model):
    __tablename__ = 'ticket'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship("User", backref="tickets")
    type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False)
    type = db.relationship("TicketType")
    paid = db.Column(db.Boolean, default=False, nullable=False)

    def __init__(self, user, type, paid=False):
        self.user = user
        self.type = type
        self.paid = paid
