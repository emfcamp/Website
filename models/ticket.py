from main import db
from decimal import Decimal

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

    def __init__(self, type=None, type_id=None, paid=False):
        if type:
            self.type = type
        elif type_id is not None:
            self.type_id = type_id
        else:
            raise ValueError('Type must be specified')

        self.paid = paid
