from main import db
from flask import current_app as app

from sqlalchemy.orm import Session
from sqlalchemy import event, or_
from sqlalchemy.exc import IntegrityError

from decimal import Decimal
from datetime import datetime, timedelta
import random
import re

safechars_lower = "2346789bcdfghjkmpqrtvwxy"

def validate_safechars(val):
    match = re.match('[%s]+' % re.escape(safechars_lower), val)
    return bool(match)

class TicketError(Exception):
    pass


class CheckinStateException(Exception):
    pass


class TicketType(db.Model):
    __tablename__ = 'ticket_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    order = db.Column(db.Integer, nullable=False)
    # admits should possible be an enum
    admits = db.Column(db.String, nullable=False)
    type_limit = db.Column(db.Integer, nullable=False)
    personal_limit = db.Column(db.Integer, nullable=False)
    has_badge = db.Column(db.Boolean, nullable=False)
    # Nullable fields
    expires = db.Column(db.DateTime)
    description = db.Column(db.String)
    discount_token = db.Column(db.String)

    # replace with capacity table?
    admits_types = ('full', 'kid', 'campervan', 'car', 'other')

    def __init__(self, id, order, admits, name, type_limit, personal_limit,
                 expires=None, discount_token=None, description=None, has_badge=True):
        if admits not in self.admits_types:
            raise Exception('unknown admission type')

        self.id = id
        self.name = name
        self.order = order
        self.admits = admits
        self.expires = expires
        self.has_badge = has_badge
        self.type_limit = type_limit
        self.description = description
        self.discount_token = discount_token
        self.personal_limit = personal_limit

    def __repr__(self):
        return "<TicketType: (Name: %s, Admits: %s, Token: %s)>" % \
            (self.name, self.admits, self.discount_token)

    def get_price(self, currency):
        for price in self.prices:
            if price.currency == currency:
                return price.value

    def get_price_ex_vat(self, currency):
        return self.get_price(currency) / Decimal('1.2')

    def is_in_date(self):
        return self.expires is None or self.expires >= datetime.utcnow()

    def is_correct_discount_token(self, discount_token):
        if not self.discount_token:
            return True
        return self.discount_token == discount_token and self.is_in_date()

    def get_sold(self, query=None):
        query = Ticket.query if query is None else query

        return query.filter_by(type=self).\
            filter(or_(Ticket.expires >= datetime.utcnow(), Ticket.paid)). \
            count()

    def get_remaining(self):
        return self.type_limit - self.get_sold()

    def user_limit(self, user, discount_token):
        if not self.is_in_date() or not self.is_correct_discount_token(discount_token):
            return 0

        if user.is_authenticated():
            # How many have been sold to this user
            user_count = self.get_sold( user.tickets )
        else:
            user_count = 0

        return min(self.personal_limit - user_count, self.get_remaining())

    @classmethod
    def get_types_for_token(cls, token, query=None):
        query = TicketType.query if query is None else query
        return query.filter_by(discount_token=token).\
                     filter(or_(TicketType.expires > datetime.utcnow(),
                                TicketType.expires.is_(None))).\
                     all()

    @classmethod
    def get_price_cheapest_full(cls, discount_token=None):
        """ Get the cheapest full ticket price. This may return
            None if there are no tickets (currently) available. """
        types = cls.get_types_for_token(discount_token,
                                        TicketType.query.filter_by(admits='full'))
        prices = [tt.get_price('GBP') for tt in types if tt.get_remaining() > 0]
        if len(prices) > 0:
            return min(prices)
        else:
            return None

    @classmethod
    def get_ticket_sales(cls):
        """ Get the number of tickets sold, by ticket type.
            Returns a dict of type -> count """
        full_tickets = TicketType.query.filter_by(admits='full').all()
        kid_tickets = TicketType.query.filter_by(admits='kid').all()
        admissions_tickets = full_tickets + kid_tickets

        ticket_totals = {}

        for ticket_type in admissions_tickets:
            ticket_totals[ticket_type] = ticket_type.get_sold()
        return ticket_totals

    @classmethod
    def get_tickets_remaining(cls):
        """ Get the total number of tickets remaining. """
        people = sum(cls.get_ticket_sales().values())
        return app.config.get('MAXIMUM_ADMISSIONS') - people


class TicketPrice(db.Model):
    __tablename__ = 'ticket_price'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False)
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


class Ticket(db.Model):
    __tablename__ = 'ticket'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type_id = db.Column(db.Integer, db.ForeignKey('ticket_type.id'), nullable=False, index=True)
    paid = db.Column(db.Boolean, default=False, nullable=False, index=True)
    expires = db.Column(db.DateTime, nullable=False)
    receipt = db.Column(db.String, unique=True)
    qrcode = db.Column(db.String, unique=True)
    emailed = db.Column(db.Boolean, default=False, nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))
    attribs = db.relationship("TicketAttrib", backref="ticket", cascade='all')
    checkin = db.relationship('TicketCheckin', uselist=False, backref='ticket', cascade='all')
    type = db.relationship('TicketType', backref='tickets')

    def __init__(self, user_id, type=None, type_id=None):
        if type:
            self.type = type
            self.type_id = type.id
        elif type_id is not None:
            self.type_id = type_id
            self.type = TicketType.query.get(type_id)
        else:
            raise ValueError('Type must be specified')

        self.user_id = user_id
        self.expires = datetime.utcnow() + timedelta(hours=2)
        self.ignore_capacity = False

    def expired(self):
        if self.paid:
            return False
        return self.expires < datetime.utcnow()

    def clone(self, new_code=None, ignore_capacity=False):
        if new_code is not None:
            raise NotImplementedError('Changing codes not yet supported')

        other = Ticket(type=self.type)
        for attrib in self.attribs:
            other.attribs.append(TicketAttrib(attrib.name, attrib.value))

        other.expires = self.expires
        other.ignore_capacity = ignore_capacity

        return other

    def create_receipt(self):
        self.create_safechars_random('receipt', 6)

    def create_qrcode(self):
        self.create_safechars_random('qrcode', 8)

    def check_in(self):
        if not self.checkin:
            self.checkin = TicketCheckin(self)
        if self.checkin.checked_in:
            raise CheckinStateException("Ticket is already checked in")

        self.checkin.checked_in = True
        db.session.commit()

    def undo_check_in(self):
        if not self.checkin:
            self.checkin = TicketCheckin(self)

        if not self.checkin.checked_in:
            raise CheckinStateException("Ticket is not yet checked in")

        self.checkin.checked_in = False
        db.session.commit()

    def badge_up(self):
        if not self.checkin:
            self.checkin = TicketCheckin(self)
        if self.checkin.badged_up:
            raise CheckinStateException("Badge is already issued")

        self.checkin.badged_up = True
        db.session.commit()

    def undo_badge_up(self):
        if not self.checkin:
            self.checkin = TicketCheckin(self)

        if not self.checkin.badged_up:
            raise CheckinStateException("Badge is not yet issued")

        self.checkin.badged_up = False
        db.session.commit()

    def create_safechars_random(self, name, length):
        if getattr(self, name) is not None:
            raise Exception('Ticket already has random value for %s' % name)

        while True:
            random.seed()
            val = ''.join(random.sample(safechars_lower, length))
            setattr(self, name, val)
            try:
                db.session.commit()
                break
            except IntegrityError:
                db.session.rollback()

    def __repr__(self):
        attrs = [self.type.admits]
        if self.paid:
            attrs.append('paid')
        if self.expired():
            attrs.append('expired')
        return "<Ticket %s: %s>" % (self.id, ', '.join(attrs))


class TicketAttrib(db.Model):
    __tablename__ = 'ticket_attrib'
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    name = db.Column(db.String, nullable=False)
    value = db.Column(db.String)

    def __init__(self, name, value=None):
        self.name = name
        self.value = value

    def __repr__(self):
        return "<TicketAttrib %s: %s>" % (self.name, self.value)


class TicketCheckin(db.Model):
    __tablename__ = 'ticket_checkin'
    ticket_id = db.Column(db.Integer, db.ForeignKey(Ticket.id), primary_key=True)
    checked_in = db.Column(db.Boolean, default=False, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    badged_up = db.Column(db.Boolean, default=False, nullable=False)

    def __init__(self, ticket):
        self.ticket = ticket

# FIXME this should probably be somewhere else as it's not really part of the model
@event.listens_for(Session, 'before_flush')
def check_capacity(session, flush_context, instances):
    tickets_in_session = {}

    for obj in session.new:
        if not isinstance(obj, Ticket):
            continue

        if obj.ignore_capacity:
            continue

        tickets_in_session[obj.type] = 1 if obj.type not in tickets_in_session \
                                         else tickets_in_session[obj.type] + 1

    if not tickets_in_session:
        # Don't block unrelated updates
        return

    full_tickets = TicketType.query.filter_by( admits='full' ).all()
    kid_tickets = TicketType.query.filter_by( admits='kid' ).all()
    admissions_tickets = full_tickets + kid_tickets

    ticket_totals = {}

    people = 0
    for type in admissions_tickets:
        sold = type.get_sold() + tickets_in_session.get(type, 0)

        people += sold
        ticket_totals[type] = sold

    if people > app.config.get('MAXIMUM_ADMISSIONS'):
        raise TicketError('No more admission tickets available')

    for type, total in ticket_totals.items():
        if total > type.type_limit:
            raise TicketError('No more tickets of type %s available' % type.name)
