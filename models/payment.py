from main import db
from sqlalchemy import event, func, column
from sqlalchemy.orm import Session, aliased
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy_continuum.utils import version_class, transaction_class

import random
import re
from decimal import Decimal, ROUND_UP
from datetime import datetime, timedelta

from . import export_attr_counts, export_intervals, bucketise
import models
from models.site_state import event_start

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
    expires = db.Column(db.DateTime, nullable=True)

    refunds = db.relationship('Refund', backref='payment', cascade='all')
    purchases = db.relationship('Purchase', backref='payment', cascade='all')

    __mapper_args__ = {'polymorphic_on': provider}

    def __init__(self, currency, amount):
        self.currency = currency
        self.amount = amount

    @classmethod
    def get_export_data(cls):
        if cls.__name__ == 'Payment':
            # Export stats for each payment type separately
            return {}

        purchase_counts = cls.query.outerjoin(cls.purchases).group_by(cls.id).with_entities(func.count(models.Ticket.id))
        refund_counts = cls.query.outerjoin(cls.refunds).group_by(cls.id).with_entities(func.count(Refund.id))

        cls_version = version_class(cls)
        cls_transaction = transaction_class(cls)
        changes = cls.query.join(cls.versions).group_by(cls.id)
        change_counts = changes.with_entities(func.count(cls_version.id))
        first_changes = changes.join(cls_version.transaction) \
                               .with_entities(func.min(cls_transaction.issued_at).label('created')) \
                               .from_self()

        cls_ver_new = aliased(cls.versions)
        cls_ver_paid = aliased(cls.versions)
        cls_txn_new = aliased(cls_version.transaction)
        cls_txn_paid = aliased(cls_version.transaction)
        active_time = func.max(cls_txn_paid.issued_at) - func.max(cls_txn_new.issued_at)
        active_times = cls.query \
            .join(cls_ver_new, cls_ver_new.id == cls.id) \
            .join(cls_ver_paid, cls_ver_paid.id == cls.id) \
            .join(cls_txn_new, cls_txn_new.id == cls_ver_new.transaction_id) \
            .join(cls_txn_paid, cls_txn_paid.id == cls_ver_paid.transaction_id) \
            .filter(cls_ver_new.state == 'new') \
            .filter(cls_ver_paid.state == 'paid') \
            .with_entities(active_time.label('active_time')) \
            .group_by(cls.id)

        time_buckets = [timedelta(0), timedelta(minutes=1), timedelta(hours=1)] + \
                       [timedelta(d) for d in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 28, 60]]

        data = {
            'public': {
                'payments': {
                    'counts': {
                        'purchases': bucketise(purchase_counts, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20]),
                        'refunds': bucketise(refund_counts, [0, 1, 2, 3, 4]),
                        'changes': bucketise(change_counts, range(10)),
                        'created_week': export_intervals(first_changes, column('created'), 'week', 'YYYY-MM-DD'),
                        'active_time': bucketise([r.active_time for r in active_times], time_buckets),
                        'amounts': bucketise(cls.query.with_entities(cls.amount_int / 100), [0, 10, 20, 30, 40, 50, 100, 150, 200]),
                    },
                },
            },
            'tables': ['payment', 'payment_version'],
        }

        count_attrs = ['state', 'reminder_sent', 'currency']
        data['public']['payments']['counts'].update(export_attr_counts(cls, count_attrs))

        return data


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

        for purchase in self.purchases:
            purchase.set_state('paid')
        self.state = 'paid'

    def cancel(self):
        if self.state == 'cancelled':
            raise StateException('Payment is already cancelled')

        elif self.state == 'refunded':
            raise StateException('Refunded payments cannot be cancelled')

        for purchase in self.purchases:
            purchase.cancel()

        self.state = 'cancelled'

    def manual_refund(self):
        # Only to be called for full out-of-band refunds, for book-keeping.
        # Providers should cancel purchases individually and insert their
        # own Refunds subclass for partial refunds.

        if self.state == 'refunded':
            raise StateException('Payment is already refunded')

        elif self.state == 'cancelled':
            # If we receive money for a cancelled payment, it will be set to paid
            raise StateException('Refunded payments cannot be cancelled')

        refund = BankRefund(self, self.amount)
        for purchase in self.purchases:
            if purchase.owner != self.user:
                raise StateException('Cannot refund transferred purchase')
            if purchase.state == 'refunded':
                raise StateException('Purchase is already refunded')
            if purchase.price_tier.get_price(self.currency) > 0 and purchase.state != 'paid':
                # This might turn out to be too strict
                raise StateException('Purchase is not paid, so cannot be refunded')
            purchase.state = 'refunded'
            purchase.refund = refund

        self.state = 'refunded'

    # TESTME
    def clone(self, ignore_capacity=False):
        other = self.__class__(self.currency, self.amount)
        for purchase in self.purchases:
            new_purchase = purchase.clone(ignore_capacity=ignore_capacity)
            self.user.purchases.append(new_purchase)
            new_purchase.payment = other

        self.user.payments.append(other)
        return other

    def invoice_number(self):
        return 'WEB-%05d' % self.id

    @property
    def expires_in(self):
        return self.expires - datetime.utcnow()


@event.listens_for(Session, 'after_flush')
def payment_change(session, flush_context):
    for obj in session.deleted:
        if isinstance(obj, Payment):
            raise Exception('Payments cannot be deleted')


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
    __export_data__ = False
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
    __export_data__ = False

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
    session_token = db.Column(db.String, unique=True)
    redirect_id = db.Column(db.String, unique=True)
    mandate = db.Column(db.String, unique=True)
    gcid = db.Column(db.String, unique=True)

    def cancel(self):
        if self.state in ['cancelled', 'refunded']:
            raise StateException('Payment has already been {}'.format(self.state))

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
        return 'EMF {} purchase'.format(event_start().year)

    def manual_refund(self):
        if self.state not in ['charged', 'paid']:
            raise StateException('Only paid or charged StripePayments can be marked as refunded')

        super(StripePayment, self).manual_refund()


class Refund(db.Model):
    __versioned__ = {}
    __tablename__ = 'refund'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)
    provider = db.Column(db.String, nullable=False)
    amount_int = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    purchases = db.relationship('Purchase', backref=db.backref('refunds', cascade='all'))

    __mapper_args__ = {'polymorphic_on': provider}

    def __init__(self, payment, amount):
        self.payment_id = payment.id
        self.payment = payment
        self.amount = amount

    @classmethod
    def get_export_data(cls):
        if cls.__name__ == 'Refund':
            # Export stats for each refund type separately
            return {}

        purchase_counts = cls.query.outerjoin(cls.purchases).group_by(cls.id).with_entities(func.count('Ticket.id'))
        data = {
            'public': {
                'refunds': {
                    'counts': {
                        'timestamp_week': export_intervals(cls.query, cls.timestamp, 'week', 'YYYY-MM-DD'),
                        'purchases': bucketise(purchase_counts, [0, 1, 2, 3, 4]),
                        'amounts': bucketise(cls.query.with_entities(cls.amount_int / 100), [0, 10, 20, 30, 40, 50, 100, 150, 200]),
                    },
                },
            },
            'tables': ['refund'],
        }

        return data


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

