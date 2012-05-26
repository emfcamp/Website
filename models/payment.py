from main import db
from base24 import tob24, fromb24, safechars
import random

class Payment(db.Model):
    __tablename__ = 'payment'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user = db.relationship("User", backref="payments")
    # TODO handle collisions
    token = db.Column(db.String, nullable=False, unique=True)
    provider = db.Column(db.String, nullable=False)
    state = db.Column(db.String, nullable=False, default='new')
    tickets = db.relationship('Ticket', lazy='dynamic', backref='payment')
    # used to stash the GoCardless object_id
    extra = db.Column(db.String, nullable=True, unique=True)

    def __init__(self, provider, user):
        self.provider = provider
        self.user = user
        # not cryptographic
        self.token = ''.join(random.sample(safechars, 4))

    @property
    def reference(self):
        return "EMF-" + self.token + "-" + tob24(self.id)

def find_payment(ref):
    if not ref.startswith("EMF-"):
        return None
    token, id = ref[4:].split("-")
    id = fromb24(str(id))
    p = Payment.query.filter_by(id=id).one()
    if p.token != token:
        return None
    return p

class PaymentChange(db.Model):
    __tablename__ = 'payment_change'
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'), nullable=False)
    payment = db.relationship("Payment", backref="changes")
    timestamp = db.Column(db.DateTime, nullable=False)
    state = db.Column(db.String, nullable=False)

    def __init__(self, state):
        self.state = state
