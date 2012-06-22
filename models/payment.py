from main import db, gocardless
from flask import url_for

import random
import re
from decimal import Decimal

safechars = "2346789BCDFGHJKMPQRTVWXY"

class Payment(db.Model):

    __tablename__ = 'payment'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    provider = db.Column(db.String, nullable=False)
    amount_pence = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String, nullable=False, default='new')
    changes = db.relationship('PaymentChange', lazy='dynamic', backref='payment')
    tickets = db.relationship('Ticket', lazy='dynamic', backref='payment', cascade='all')
    __mapper_args__ = {'polymorphic_on': provider}

    def __init__(self, amount):
        self.amount = amount

    @property
    def amount(self):
        return Decimal(self.amount_pence) / 100

    @amount.setter
    def amount(self, val):
        self.amount_pence = int(val * 100)


class BankPayment(Payment):
    name = 'Bank transfer'

    __mapper_args__ = {'polymorphic_identity': 'banktransfer'}
    bankref = db.Column(db.String, unique=True)

    def __init__(self, amount):
        Payment.__init__(self, amount)

        # not cryptographic
        self.bankref = ''.join(random.sample(safechars, 8))

    def __repr__(self):
        return "<BankPayment: %s %s>" % (self.state, self.bankref)

class GoCardlessPayment(Payment):
    name = 'GoCardless payment'

    __mapper_args__ = {'polymorphic_identity': 'gocardless'}
    gcid = db.Column(db.String, unique=True)

    def bill_url(self, name):
        return gocardless.client.new_bill_url(self.amount, name=name,
            redirect_uri=url_for('gocardless_complete', payment=self.id, _external=True),
            cancel_uri=url_for('gocardless_cancel', payment=self.id, _external=True))


class PaymentChange(db.Model):
    __tablename__ = 'payment_change'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    state = db.Column(db.String, nullable=False)

    def __init__(self, state):
        self.state = state
