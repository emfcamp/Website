from main import db
from decimal import Decimal
from datetime import datetime, timedelta
import random

from sqlalchemy.orm import Session
from sqlalchemy import event, or_
from sqlalchemy.exc import IntegrityError

safechars_lower = "2346789bcdfghjkmpqrtvwxy"


class TicketError(Exception):
    pass


class TicketType(db.Model):
    __tablename__ = 'ticket_type'
    code = db.Column(db.String, primary_key=True)
    name = db.Column(db.String, nullable=False)
    notice = db.Column(db.String)
    capacity = db.Column(db.Integer, nullable=False)
    limit = db.Column(db.Integer, nullable=False)
    order = db.Column(db.Integer, nullable=False)

    def __init__(self, code, name, capacity, limit, order, notice=None):
        self.code = code
        self.name = name
        self.capacity = capacity
        self.limit = limit
        self.order = order
        self.notice = notice

    def __repr__(self):
        return "<TicketType: %s>" % (self.name)

    def get_price(self, currency):
        for price in self.prices:
            if price.currency == currency:
                return price.value

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


class TicketPrice(db.Model):
    __tablename__ = 'ticket_price'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.Integer, db.ForeignKey('ticket_type.code'), nullable=False)
    currency = db.Column(db.String, nullable=False)
    price_int = db.Column(db.Integer, nullable=False)
    type = db.relationship(TicketType, backref="prices")

    def __init__(self, currency, price):
        self.currency = currency
        self.value = price

    @property
    def value(self):
        return Decimal(self.price_int) / 100

    @value.setter
    def value(self, val):
        self.price_int = int(val * 100)


class TicketToken(db.Model):
    __tablename__ = 'ticket_token'
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String, nullable=False, index=True)
    expires = db.Column(db.DateTime, nullable=False)
    code = db.Column(db.Integer, db.ForeignKey('ticket_type.code'), nullable=False)
    type = db.relationship(TicketType, backref="tokens")

    def __init__(self, token, expires):
        self.token = token
        self.expires = expires

    @classmethod
    def types(cls, token):
        if not token:
            return []
        tokens = TicketToken.query.filter_by(token=token). \
            filter(TicketToken.expires > datetime.utcnow())
        ticket_types = [t.type for t in tokens.all()]
        return ticket_types


class Ticket(db.Model):
    __tablename__ = 'ticket'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    code = db.Column(db.Integer, db.ForeignKey('ticket_type.code'), nullable=False, index=True)
    paid = db.Column(db.Boolean, default=False, nullable=False)
    expires = db.Column(db.DateTime, nullable=False)
    receipt = db.Column(db.String, unique=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))
    attribs = db.relationship("TicketAttrib", backref="ticket", cascade='all')
    type = db.relationship(TicketType, backref="tickets")

    def __init__(self, type=None, code=None):
        if type:
            self.type = type
            self.code = type.code
        elif code is not None:
            self.code = code
            self.type = TicketType.query.get(code)
        else:
            raise ValueError('Type must be specified')

        self.expires = datetime.utcnow() + timedelta(hours=2)

    def expired(self):
        if self.paid:
            return False
        return self.expires < datetime.utcnow()

    def create_receipt(self):
        while True:
            random.seed()
            self.receipt = ''.join(random.sample(safechars_lower, 6))
            try:
                db.session.commit()
                break
            except IntegrityError:
                db.session.rollback()

    def __repr__(self):
        return "<Ticket: %s, type: %s, paid? %s, expired: %s>" % (self.id, self.code, self.paid, str(self.expired()))

class TicketAttrib(db.Model):
    __tablename__ = 'ticket_attrib'
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

    if not totals:
        # Don't block unrelated updates
        return

    # Any admission tickets count towards the full ticket total
    fulls = TicketType.query.filter(TicketType.code.like('full%')).all()
    kids = TicketType.query.filter(TicketType.code.like('kids%')).all()
    admission_types = fulls + kids
    people = sum((totals.get(type, 0) for type in admission_types))

    if people > TicketType.query.get('full').capacity:
        raise TicketError('No more admission tickets available')

    for type, count in totals.items():

        if count > type.capacity:
            raise TicketError('No more tickets of type %s available') % type.name
