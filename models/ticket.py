from main import db
from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.orm import attributes, Session
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import event, or_

class ConstTicketType(object):
    def __init__(self, name):
        self.name = name
        self.val = None

    def __get__(self, obj, objtype):
        return objtype.query.filter_by(name=self.name).one()

class TicketType(db.Model):
    __tablename__ = 'ticket_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    notice = db.Column(db.String)
    capacity = db.Column(db.Integer, nullable=False)
    limit = db.Column(db.Integer, nullable=False)
    cost_pence = db.Column(db.Integer, nullable=False)
    tickets = db.relationship("Ticket", backref="type")

    def __init__(self, name, capacity, limit, cost, notice=None):
        self.name = name
        self.capacity = capacity
        self.limit = limit
        self.cost = cost
        self.notice = notice

    def __repr__(self):
        return "<TicketType: %s>" % (self.name)

    @property
    def cost(self):
        return Decimal(self.cost_pence) / 100

    @cost.setter
    def cost(self, val):
        self.cost_pence = int(val * 100)

    def user_limit(self, user):
        if user.is_authenticated():
            user_count = user.tickets. \
                filter_by(type=self). \
                filter(or_(Ticket.expires >= datetime.utcnow(), Ticket.paid)). \
                count()
        else:
            user_count = 0

        count = Ticket.query.filter_by(type=self). \
            filter(or_(Ticket.expires >= datetime.utcnow(), Ticket.paid)). \
            count()

        return min(self.limit - user_count, self.capacity - count)

    Prepay = ConstTicketType('Prepay Camp Ticket')
    FullPrepay = ConstTicketType('Full Camp Ticket (prepay)')
    Full = ConstTicketType('Full Camp Ticket')
    Under18 = ConstTicketType('Under-18 Camp Ticket')


class Ticket(db.Model):
    __tablename__ = 'ticket'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False)
    paid = db.Column(db.Boolean, default=False, nullable=False)
    expires = db.Column(db.DateTime, nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))
    attribs = db.relationship("TicketAttrib", backref="ticket", cascade='all')

    def __init__(self, type=None, type_id=None):
        if type:
            self.type = type
            self.type_id = type.id
        elif type_id is not None:
            self.type_id = type_id
            self.type = TicketType.query.get(type_id)
        else:
            raise ValueError('Type must be specified')

        self.expires = datetime.utcnow() + timedelta(hours=2)

    def expired(self):
        if self.paid:
            return False
        return self.expires < datetime.utcnow()
    
    def __repr__(self):
        return "<Ticket: %s, type: %s, paid? %s, expired: %s>" % (self.id, self.type_id, self.paid, str(self.expired()))

class TicketAttrib(db.Model):
    __tablename__ = 'ticketattrib'
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    name = db.Column(db.String, nullable=False)
    value = db.Column(db.String)

    def __init__(self, name, value=None):
        self.name = name
        self.value = value

@event.listens_for(Session, 'before_flush')
def check_capacity(session, flush_context, instances):
    totals = {}

    for obj in session.new:
        if not isinstance(obj, Ticket):
            continue

        if obj.type not in totals:
            totals[obj.type] = Ticket.query.filter_by(type=obj.type). \
                filter(or_(Ticket.expires >= datetime.utcnow(), Ticket.paid)). \
                count()

        totals[obj.type] += 1

    if len(totals) == 0:
        # hack for empty database when creating tickets
        return

    # Any admission tickets count towards the full ticket total
    AdmissionTypes = [TicketType.FullPrepay, TicketType.Full, TicketType.Under18]
    people = sum((totals.get(type, 0) for type in AdmissionTypes))

    if people > TicketType.Full.capacity:
        raise TicketError('No more admission tickets available')

    for type, count in totals.items():

        if count > type.capacity:
            raise TicketError('No more tickets of type %s available') % type.name

