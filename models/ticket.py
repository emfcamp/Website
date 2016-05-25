from main import db, cache
from flask import current_app as app
from models.payment import Payment

from sqlalchemy.orm import Session, column_property
from sqlalchemy import event, or_, and_, func
from sqlalchemy.exc import IntegrityError

from decimal import Decimal
from datetime import datetime, timedelta
import random
import re

safechars_lower = "2346789bcdfghjkmpqrtvwxy"

def validate_safechars(val):
    match = re.match('[%s]+' % re.escape(safechars_lower), val)
    return bool(match)

class TicketLimitException(Exception):
    pass

class CheckinStateException(Exception):
    pass


class TicketType(db.Model):
    __tablename__ = 'ticket_type'
    id = db.Column(db.Integer, primary_key=True)
    fixed_id = db.Column(db.Integer, unique=True)
    name = db.Column(db.String, nullable=False)
    order = db.Column(db.Integer, nullable=False)
    # admits should possible be an enum
    admits = db.Column(db.String, nullable=False)
    type_limit = db.Column(db.Integer, nullable=False)
    personal_limit = db.Column(db.Integer, nullable=False)
    has_badge = db.Column(db.Boolean, nullable=False)
    is_transferable = db.Column(db.Boolean, default=True, nullable=False)
    # Nullable fields
    expires = db.Column(db.DateTime)
    expired = column_property(and_(~expires.is_(None), expires < func.now()))
    description = db.Column(db.String)
    discount_token = db.Column(db.String)

    # replace with capacity table?
    admits_types = ('full', 'kid', 'campervan', 'car', 'other')

    def __init__(self, order, admits, name, type_limit, personal_limit,
                 expires=None, discount_token=None, description=None,
                 has_badge=True, is_transferable=True):

        if admits not in self.admits_types:
            raise Exception('unknown admission type')

        self.name = name
        self.order = order
        self.admits = admits
        self.expires = expires
        self.has_badge = has_badge
        self.type_limit = type_limit
        self.description = description
        self.discount_token = discount_token
        self.personal_limit = personal_limit
        self.is_transferable = is_transferable

    def __repr__(self):
        if self.fixed_id is not None:
            clsname = 'FixedTicketType %s' % self.fixed_id
        else:
            clsname = 'TicketType %s' % self.id

        return "<%s: %s>" % (clsname, self.name)

    def get_price(self, currency):
        for price in self.prices:
            if price.currency == currency:
                return price.value

    def get_price_ex_vat(self, currency):
        return self.get_price(currency) / Decimal('1.2')

    def get_sold(self, query=None):
        if query is None:
            query = Ticket.query

        # A ticket is sold if it's set to paid, or if it's reserved
        # (there's a valid payment associated with it)
        sold_tickets = query.filter(
            Ticket.type == self,
            or_(Ticket.paid,
                Payment.query.filter(
                    Payment.state != 'new',
                    Payment.state != 'cancelled',
                ).filter(Payment.tickets.expression).exists())
        )

        return sold_tickets

    def get_remaining(self):
        if self.expired:
            return 0
        return self.type_limit - self.get_sold().count()

    def user_limit(self, user, discount_token):
        if self.expired:
            return 0

        # Why do we need to check this?
        if self.discount_token != discount_token:
            return 0

        if user.is_authenticated():
            # How many have been sold to this user
            user_count = self.get_sold(user.tickets).count()
        else:
            user_count = 0

        return min(self.personal_limit - user_count, self.get_remaining())

    @classmethod
    def get_types_for_token(cls, token):
        return TicketType.query.filter_by(discount_token=token, expired=False).all()

    @classmethod
    @cache.memoize(timeout=60)
    def get_price_cheapest_full(cls):
        """ Get the cheapest full ticket price. This may return
            None if there are no tickets (currently) available. """
        types = TicketType.query.filter_by(admits='full', discount_token=None)
        prices = [tt.get_price('GBP') for tt in types if tt.get_remaining() > 0 and
                                                         'supporter' not in tt.name.lower()]
        if len(prices) > 0:
            return min(prices)
        else:
            return None

    @classmethod
    def get_ticket_sales(cls):
        """ Get the number of tickets sold, by ticket type.
            Returns a dict of type -> count """
        # FIXME: should this filter by payment type?
        full_tickets = TicketType.query.filter_by(admits='full').all()
        kid_tickets = TicketType.query.filter_by(admits='kid').all()
        admissions_tickets = full_tickets + kid_tickets

        ticket_totals = {}

        for ticket_type in admissions_tickets:
            ticket_totals[ticket_type] = ticket_type.get_sold().count()
        return ticket_totals

    @classmethod
    def get_tickets_remaining(cls):
        """ Get the total number of tickets remaining. """
        total = Payment.query.filter(
            Payment.state != 'new',
            Payment.state != 'cancelled',
        ).join(Ticket).join(Ticket.type).filter(or_(TicketType.admits == 'full',
                                                    TicketType.admits == 'kid')).count()
        return app.config.get('MAXIMUM_ADMISSIONS') - total


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
    expired = column_property(and_(expires < func.now(), paid == False))  # noqa
    receipt = db.Column(db.String, unique=True)
    qrcode = db.Column(db.String, unique=True)
    emailed = db.Column(db.Boolean, default=False, nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))
    attribs = db.relationship("TicketAttrib", backref="ticket", cascade='all')
    transfers = db.relationship('TicketTransfer', backref='ticket')
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
        if self.expired:
            attrs.append('expired')
        return "<Ticket %s: %s>" % (self.id, ', '.join(attrs))

    def transfer(self, from_user, to_user):
        """
        Change the user a ticket is assigned to and remove the qrcode/receipt so
        that the old values can't be used.
        """
        if not self.type.is_transferable:
            raise Exception('This ticket cannot be transferred.')
        self.user = to_user
        self.emailed = False
        self.qrcode = None
        self.receipt = None

        db.session.add(TicketTransfer(self, to_user, from_user))
        db.session.commit()


class TicketTransfer(db.Model):
    __tablename__ = 'ticket_transfer'
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __init__(self, ticket, to_user, from_user):
        if to_user.id == from_user.id:
            raise Exception('"From" and "To" users must be different.')
        self.ticket_id = ticket.id
        self.to_user_id = to_user.id
        self.from_user_id = from_user.id

    def __repr__(self):
        return "<Transfer Ticket: %s from %s to %s on %s>" % (
            self.ticket_id, self.from_user_id, self.to_user_id, self.datetime)


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

@event.listens_for(Session, 'before_flush')
def check_capacity(session, flush_context, instances):
    tt_totals = {}

    for obj in session.new:
        if not isinstance(obj, Ticket):
            continue

        if obj.ignore_capacity:
            continue

        tt = obj.type

        if tt not in tt_totals:
            tt_totals[tt] = tt.get_sold().count()

        tt_totals[tt] += 1

    if not tt_totals:
        # Don't block unrelated updates
        return

    total_admissions = 0
    for tt, total in tt_totals.items():
        if total > tt.type_limit:
            app.logger.warn('Total tickets of type %s (%s) %s > %s', tt.id, tt.name, total, tt.type_limit)
            raise TicketLimitException('Ticket limit exceeded for %s' % tt.name)

        if tt.admits in ['full', 'kid']:
            total_admissions += total

    if total_admissions > app.config.get('MAXIMUM_ADMISSIONS'):
        raise TicketLimitException('No more admission tickets available')

