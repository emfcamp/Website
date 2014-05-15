from main import db, gocardless
from flask import url_for
from sqlalchemy import event
from sqlalchemy.orm import attributes, Session
from sqlalchemy.orm.attributes import get_history

import random
import re
from decimal import Decimal
from datetime import datetime

safechars = "2346789BCDFGHJKMPQRTVWXY"

class Payment(db.Model):

    __tablename__ = 'payment'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    provider = db.Column(db.String, nullable=False)
    currency = db.Column(db.String, nullable=False)
    amount_int = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String, nullable=False, default='new')
    changes = db.relationship('PaymentChange', backref='payment')
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

class GoCardlessPayment(Payment):
    name = 'GoCardless payment'

    __mapper_args__ = {'polymorphic_identity': 'gocardless'}
    gcid = db.Column(db.String, unique=True)

    def bill_url(self, name):
        return gocardless.client.new_bill_url(self.amount, name=name,
            redirect_uri=url_for('gocardless_complete', payment_id=self.id, _external=True),
            cancel_uri=url_for('gocardless_cancel', payment_id=self.id, _external=True))


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
            change = PaymentChange(obj, obj.state)

    for obj in session.dirty:
        if isinstance(obj, Payment):
            state = get_history(obj, 'state').added[0]
            change = PaymentChange(obj, state)

    for obj in session.deleted:
        if isinstance(obj, Payment):
            raise Exception('Payments cannot be deleted');

