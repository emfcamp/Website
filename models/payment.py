from main import db, gocardless, external_url
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import get_history
from sqlalchemy.orm.exc import NoResultFound

import random
import re
from decimal import Decimal, ROUND_UP
from datetime import datetime

safechars = "2346789BCDFGHJKMPQRTVWXY"

class StateException(Exception):
    pass


class Payment(db.Model):

    __tablename__ = 'payment'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    provider = db.Column(db.String, nullable=False)
    currency = db.Column(db.String, nullable=False)
    amount_int = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String, nullable=False, default='new')
    reminder_sent = db.Column(db.Boolean, nullable=False, default=False)
    changes = db.relationship('PaymentChange', backref='payment',
                              order_by='PaymentChange.timestamp, PaymentChange.id')
    tickets = db.relationship('Ticket', lazy='dynamic', backref='payment', cascade='all')
    __mapper_args__ = {'polymorphic_on': provider}

    def __init__(self, currency, amount):
        self.currency = currency
        self.amount = amount

    @property
    def amount(self):
        return Decimal(self.amount_int) / 100

    @amount.setter
    def amount(self, val):
        self.amount_int = int(val * 100)

    @classmethod
    def premium(cls, currency, amount):
        if not hasattr(cls, 'premium_percent'):
            return Decimal(0)

        amount_int = int(amount * 100)
        premium = Decimal(cls.premium_percent) / 100 * amount_int
        premium = premium.quantize(Decimal(1), ROUND_UP)
        return premium / 100

    def paid(self):
        if self.state == 'paid':
            raise StateException('Payment %s already paid' % self.id)

        for ticket in self.tickets:
            ticket.paid = True
        self.state = 'paid'

    def cancel(self):
        if self.state == 'cancelled':
            raise StateException('Payment %s already cancelled' % self.id)

        for ticket in self.tickets:
            ticket.expires = datetime.utcnow()
            ticket.paid = false
        self.state = 'cancelled'

    def clone(self, new_user=None, ignore_capacity=False):
        if new_user is not None:
            raise NotImplementedError('Changing users not yet supported')

        other = self.__class__(self.currency, self.amount)
        for ticket in self.tickets:
            new_ticket = ticket.clone(ignore_capacity=ignore_capacity)
            self.user.tickets.append(new_ticket)
            new_ticket.payment = other

        self.user.payments.append(other)
        return other

    def invoice_number(self):
        return 'WEB-%05d' % self.id


class BankPayment(Payment):
    name = 'Bank transfer'

    __mapper_args__ = {'polymorphic_identity': 'banktransfer'}
    bankref = db.Column(db.String, unique=True)

    def __init__(self, currency, amount):
        Payment.__init__(self, currency, amount)

        # not cryptographic
        self.bankref = ''.join(random.sample(safechars, 8))

    def __repr__(self):
        return "<BankPayment: %s %s>" % (self.state, self.bankref)


class BankAccount(db.Model):
    __tablename__ = 'bank_account'
    id = db.Column(db.Integer, primary_key=True)
    sort_code = db.Column(db.String, nullable=False)
    acct_id = db.Column(db.String, nullable=False)
    currency = db.Column(db.String, nullable=False)

    def __init__(self, sort_code, acct_id, currency='GBP'):
        self.sort_code = sort_code
        self.acct_id = acct_id
        self.currency = currency

    @classmethod
    def get(cls, sort_code, acct_id):
        return cls.query.filter_by(acct_id=acct_id, sort_code=sort_code).one()

db.Index('ix_bank_account_sort_code_acct_id', BankAccount.sort_code, BankAccount.acct_id, unique=True)

class BankTransaction(db.Model):
    __tablename__ = 'bank_transaction'

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey(BankAccount.id), nullable=False)
    posted = db.Column(db.DateTime, nullable=False)
    type = db.Column(db.String, nullable=False)
    amount_int = db.Column(db.Integer, nullable=False)
    fit_id = db.Column(db.String, index=True)  # allegedly unique, but don't trust it
    payee = db.Column(db.String, nullable=False)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))
    suppressed = db.Column(db.Boolean, nullable=False, default=False)
    account = db.relationship(BankAccount, backref='transactions')
    payment = db.relationship(BankPayment, backref='transactions')

    def __init__(self, account_id, posted, type, amount, payee, fit_id=None):
        self.account_id = account_id
        self.posted = posted
        self.type = type
        self.amount = amount
        self.payee = payee
        self.fit_id = fit_id

    def __repr__(self):
        return "<BankTransaction: %s, %s>" % (self.amount, self.payee)

    @property
    def amount(self):
        return Decimal(self.amount_int) / 100

    @amount.setter
    def amount(self, val):
        self.amount_int = int(val * 100)

    def get_matching(self):
        # fit_ids can change, and payments can be reposted
        matching = self.query.filter_by(
            account_id=self.account_id,
            posted=self.posted,
            type=self.type,
            amount_int=self.amount_int,
            payee=self.payee,
        )
        return matching

    def match_payment(self):
        """
        We need to deal with human error and character deletion without colliding.
        Unless we use some sort of coding, the minimum length of a bankref should
        be 8, although 7 is workable. For reference:

                    Transactions
        Keyspace    10^2  10^3  10^4
        24^8 ~2^36  2^24  2^18  2^11
        24^7 ~2^32  2^20  2^13  2^7
        24^6 ~2^28  2^15  2^9   2^2
        24^5 ~2^23  2^11  2^4   2^-3

        For GBP transactions, we tend to see:

          name ref type

        where type is BGC or BBP.

        For EUR, it's:

          name*serial*ref

        where serial is a 6-digit number, and ref is often the payee
        name again, or REFERENCE, and always truncated to 8 chars.
        """

        ref = self.payee.upper()

        found = re.findall('[%s]{4}[- ]?[%s]{4}' % (safechars, safechars), ref)
        for f in found:
            bankref = f.replace('-', '').replace(' ', '')
            try:
                return BankPayment.query.filter_by(bankref=bankref).one()
            except NoResultFound:
                continue

        # It's pretty safe to match against the last character being lost
        found = re.findall('[%s]{4}[- ]?[%s]{3}' % (safechars, safechars), ref)
        for f in found:
            bankref = f.replace('-', '').replace(' ', '')
            try:
                return BankPayment.query.filter( BankPayment.bankref.startswith(bankref) ).one()
            except NoResultFound:
                continue

        return None


db.Index('ix_bank_transaction_u1',
         BankTransaction.account_id,
         BankTransaction.posted,
         BankTransaction.type,
         BankTransaction.amount_int,
         BankTransaction.payee,
         BankTransaction.fit_id,
         unique=True)

class GoCardlessPayment(Payment):
    name = 'GoCardless payment'

    __mapper_args__ = {'polymorphic_identity': 'gocardless'}
    gcid = db.Column(db.String, unique=True)

    def bill_url(self, name):
        # TODO: check country
        bill_url = gocardless.client.new_bill_url(
            amount=self.amount,
            name=name,
            redirect_uri=external_url('gocardless_complete', payment_id=self.id),
            cancel_uri=external_url('gocardless_cancel', payment_id=self.id),
            currency=self.currency,
        )

        return bill_url

class StripePayment(Payment):
    name = 'Stripe payment'
    premium_percent = 5

    __mapper_args__ = {'polymorphic_identity': 'stripe'}
    chargeid = db.Column(db.String, unique=True)
    token = db.Column(db.String)

    @property
    def description(self):
        return 'EMF 2014 tickets'


class PaymentChange(db.Model):
    __tablename__ = 'payment_change'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    state = db.Column(db.String, nullable=False)

    def __init__(self, payment, state):
        self.payment = payment
        self.state = state


@event.listens_for(Session, 'after_flush')
def payment_change(session, flush_context):
    for obj in session.new:
        if isinstance(obj, Payment):
            PaymentChange(obj, obj.state)

    for obj in session.dirty:
        if isinstance(obj, Payment):
            added = get_history(obj, 'state').added
            if added:
                PaymentChange(obj, added[0])

    for obj in session.deleted:
        if isinstance(obj, Payment):
            raise Exception('Payments cannot be deleted')
