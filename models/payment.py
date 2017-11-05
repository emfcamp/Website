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
    __versioned__ = {}
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    provider = db.Column(db.String, nullable=False)
    currency = db.Column(db.String, nullable=False)
    amount_int = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String, nullable=False, default='new')
    reminder_sent = db.Column(db.Boolean, nullable=False, default=False)
    changes = db.relationship('PaymentChange', backref='payment',
                              order_by='PaymentChange.timestamp, PaymentChange.id')
    refunds = db.relationship('Refund', lazy='dynamic', backref='payment', cascade='all')
    purchases = db.relationship('Purchase', lazy='dynamic', backref='payment',
                             primaryjoin='Purchase.payment_id == Payment.id',
                             cascade='all')

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
        if amount is None:
            return None

        amount_int = int(amount * 100)
        premium = Decimal(cls.premium_percent) / 100 * amount_int
        premium = premium.quantize(Decimal(1), ROUND_UP)
        return premium / 100

    @classmethod
    def premium_refund(cls, currency, amount):
        # Just use the default calculation
        return cls.premium(currency, amount)

    def paid(self):
        if self.state == 'paid':
            raise StateException('Payment is already paid')

        for ticket in self.tickets:
            ticket.paid = True
        self.state = 'paid'

    def cancel(self):
        if self.state == 'cancelled':
            raise StateException('Payment is already cancelled')

        elif self.state == 'refunded':
            raise StateException('Refunded payments cannot be cancelled')

        now = datetime.utcnow()
        for ticket in self.tickets:
            ticket.paid = False
            if ticket.expires is None or ticket.expires > now:
                ticket.expires = now

        self.state = 'cancelled'

    def manual_refund(self):
        # Only to be called for full out-of-band refunds, for book-keeping.
        # Providers should cancel tickets individually and insert their
        # own Refunds subclass for partial refunds.

        if self.state == 'refunded':
            raise StateException('Payment is already refunded')

        elif self.state == 'cancelled':
            # If we receive money for a cancelled payment, it will be set to paid
            raise StateException('Refunded payments cannot be cancelled')

        refund = BankRefund(self, self.amount)
        now = datetime.utcnow()
        for ticket in self.tickets:
            if ticket.user != self.user:
                raise StateException('Cannot refund transferred ticket')
            if ticket.expires is None or ticket.expires > now:
                ticket.expires = now
            if ticket.refund is not None:
                raise StateException('Ticket is already refunded')
            if ticket.type.get_price(self.currency) and not ticket.paid:
                # This might turn out to be too strict
                raise StateException('Ticket is not paid, so cannot be refunded')
            ticket.paid = False
            ticket.refund = refund

        self.state = 'refunded'

    def clone(self, ignore_capacity=False):
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

    def manual_refund(self):
        if self.state != 'paid':
            raise StateException('Only paid BankPayments can be marked as refunded')

        super(BankPayment, self).manual_refund()


class BankAccount(db.Model):
    __tablename__ = 'bank_account'
    __versioned__ = {}
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
    __versioned__ = {}
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
            user={
                'email': self.user.email
            },
            redirect_uri=external_url('payments.gocardless_complete', payment_id=self.id),
            cancel_uri=external_url('payments.gocardless_cancel', payment_id=self.id),
            currency=self.currency,
        )

        return bill_url

    def cancel(self):
        if self.state == 'new':
            # No bill to check
            pass

        elif self.state in ['cancelled', 'refunded']:
            # Don't cancel the debit before raising
            pass

        else:
            # FIXME: move this out to the app
            bill = gocardless.client.bill(self.gcid)

            if bill.can_be_cancelled:
                bill.cancel()
            elif bill.status != 'cancelled':
                raise StateException('GoCardless will not allow this bill to be cancelled')

        super(GoCardlessPayment, self).cancel()

    def manual_refund(self):
        # https://help.gocardless.com/customer/portal/articles/1580207
        # "At the moment, it isn't usually possible to refund a customer via GoCardless"
        if self.state != 'paid':
            raise StateException('Only paid GoCardless payments can be marked as refunded')

        super(GoCardlessPayment, self).manual_refund()


class StripePayment(Payment):
    name = 'Stripe payment'
    premium_percent = 5

    __mapper_args__ = {'polymorphic_identity': 'stripe'}
    chargeid = db.Column(db.String, unique=True)
    token = db.Column(db.String)

    def cancel(self):
        if self.state in ['charged', 'paid']:
            raise StateException('Cannot automatically cancel charging/charged Stripe payments')

        super(StripePayment, self).cancel()

    @property
    def description(self):
        return 'EMF 2016 tickets'

    def manual_refund(self):
        if self.state not in ['charged', 'paid']:
            raise StateException('Only paid or charged StripePayments can be marked as refunded')

        super(StripePayment, self).manual_refund()


class PaymentChange(db.Model):
    __versioned__ = {}
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


class Refund(db.Model):
    __versioned__ = {}
    __tablename__ = 'refund'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)
    provider = db.Column(db.String, nullable=False)
    amount_int = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    puchases = db.relationship('Purchase', lazy='dynamic', backref='refunds',
                               primaryjoin='Purchase.refund_id == Refund.id',
                               cascade='all')
    __mapper_args__ = {'polymorphic_on': provider}

    def __init__(self, payment, amount):
        self.payment_id = payment.id
        self.payment = payment
        self.amount = amount

    @property
    def amount(self):
        return Decimal(self.amount_int) / 100

    @amount.setter
    def amount(self, val):
        self.amount_int = int(val * 100)


class BankRefund(Refund):
    __mapper_args__ = {'polymorphic_identity': 'banktransfer'}

class StripeRefund(Refund):
    __mapper_args__ = {'polymorphic_identity': 'stripe'}
    refundid = db.Column(db.String, unique=True)


class StripeRefundOld(db.Model):
    __versioned__ = {}
    __tablename__ = 'stripe_refund'
    id = db.Column(db.Integer, primary_key=True)
    refundid = db.Column(db.String, unique=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)

    def __init__(self, payment):
        self.payment = payment

