from main import db
from decimal import Decimal
from datetime import datetime, timedelta


class TicketType(db.Model):
    __tablename__ = 'ticket_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    limit = db.Column(db.Integer, nullable=False)
    cost_pence = db.Column(db.Integer, nullable=False)
    tickets = db.relationship("Ticket", backref="type")

    def __init__(self, name, capacity, limit, cost):
        self.name = name
        self.capacity = capacity
        self.limit = limit
        self.cost = cost

    @property
    def cost(self):
        return Decimal(self.cost_pence) / 100

    @cost.setter
    def cost(self, val):
        self.cost_pence = int(val * 100)

class Ticket(db.Model):
    __tablename__ = 'ticket'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False)
    paid = db.Column(db.Boolean, default=False, nullable=False)
    expires = db.Column(db.DateTime, nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)

    def __init__(self, type=None, type_id=None, paid=False, payment=None):
        if type:
            self.type = type
        elif type_id is not None:
            self.type_id = type_id
        else:
            raise ValueError('Type must be specified')

        if payment is None:
            raise ValueError('Payment must be specified')

        self.paid = paid
        self.expires = datetime.utcnow() + timedelta(days=10)
        self.payment = payment

    def expired(self):
        # can't be expired if it's been paid!
        if self.paid:
            return False
        return self.expires < datetime.utcnow()
    
    def __repr__(self):
        return "<Ticket: %d, type: %d, paid? %d, expired: %s>" % (self.id, self.type_id, self.paid, str(self.expired()))
