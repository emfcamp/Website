# coding=utf-8
from decimal import Decimal
from datetime import datetime, timedelta

from main import db

from sqlalchemy import UniqueConstraint, and_, func
from sqlalchemy.orm import column_property

# state: [allowed next state, ] pairs
PRODUCT_INSTANCE_STATES = { 'reserved': ['payment-pending', 'expired'],
                            'payment-pending': ['expired', 'paid'],
                            'expired': [],
                            'paid': ['checked-in', 'refunded'],
                            'refunded': [],
                            # allow undoing of check-in
                            'checked-in': ['paid'],
                            }
allowed_states = list(PRODUCT_INSTANCE_STATES.keys())

# In hours
PRODUCT_INSTANCE_EXPIRY_TIME = 2


class ProductInstanceStateException(Exception):
    pass


class ProductGroupException(Exception):
    pass

class ProductGroup(db.Model):
    __tablename__ = "product_group"
    __mapper_args__ = {
        'polymorphic_on': 'type',
        'polymorphic_identity': 'product_group',
    }

    # This is a self referential table. Types have a parent type which
    # they also validate against.
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("product_group.id"))
    type = db.Column(db.String, nullable=False)

    name = db.Column(db.String, unique=True, nullable=False)
    description = db.Column(db.String)

    expires = db.Column(db.DateTime)
    __expired = column_property(and_(~expires.is_(None), expires < func.now()))
    # A max capacity of -1 implies no max (use parent"s if set)
    capacity_max = db.Column(db.Integer, default=-1)
    capacity_used = db.Column(db.Integer, default=0)
    capacity_remaining = column_property(capacity_max - capacity_used)
    discount_token = db.Column(db.String)

    parent = db.relationship("ProductGroup", remote_side=[id], backref="children", cascade="all")

    db.CheckConstraint("capacity_used <= capacity_max", "within_capacity")

    def __init__(self, name, parent=None, discount_token='', **kwargs):
        # Check for the pathological case that of setting a discount token on
        # a group with a parent that already has a token.
        if discount_token and parent and not parent.token_correct(discount_token):
            raise ProductGroupException('Parent and child tokens must be the same.')
        super().__init__(name=name, parent=parent, discount_token=discount_token,
                         **kwargs)

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self.name)

    def get_counts_by_state(self, states_to_get=allowed_states, res={}):
        if len(res) == 0:
            res = {s: 0 for s in states_to_get}

        for child in self.children:
            res = child.get_counts_by_state(states_to_get, res)
        return res

    def get_sold(self):
        return self.get_counts_by_state(['paid', 'checked-in'])

    def has_capacity(self, count=1):
        """
        Determine whether this ProductGroup, and all its ancestors, have
        available capacity.

        The count parameter (default: 1) determines whether there is capacity
        for count instances.
        """
        if count < 1:
            raise ValueError("Count cannot be less than 1.")

        if self.parent and not self.parent.has_capacity():
            return False

        if self.capacity_max >= 0:
            return (self.capacity_used + count) <= self.capacity_max
        return True

    def has_expired(self):
        """
        Determine whether this ProductGroup, and any of its ancestors, have
        expired.
        """
        if self.parent and self.parent.has_expired():
            return True

        return self.expires and self.expires < datetime.utcnow()

    def token_correct(self, token):
        if self.parent and not self.parent.token_correct(token):
            return False

        return (not self.discount_token) or (self.discount_token == token)

    def issue_instances(self, count=1, token=''):
        """
        If possible (i.e. the ProductGroup has not expired and has capacity)
        reduce the available capacity by count.
        """
        if not self.has_capacity(count):
            raise ProductGroupException("ProductGroup is out of capacity.")

        if self.has_expired():
            raise ProductGroupException("ProductGroup has expired.")

        if not self.token_correct(token):
            raise ProductGroupException("Incorrect discount token.")

        if self.parent:
            self.parent.issue_instances(count, token)
        self.capacity_used += count

    def return_instances(self, count=1):
        """
        Reintroduce previously used capacity
        """
        if count < 1:
            raise ValueError("Count cannot be less than 1.")
        self.parent.return_instances(count)
        self.capacity_used -= count

    # This is mostly used in testing...
    @classmethod
    def get_by_name(cls, name):
        return ProductGroup.query.filter_by(name=name).first()

    @classmethod
    def get_product_groups_for_token(cls, token):
        return ProductGroup.query.filter_by(discount_token=token, __expired=False).all()


class PriceTier(ProductGroup):
    __mapper_args__ = {'polymorphic_identity': 'price_tier'}

    def get_counts_by_state(self, states_to_get=allowed_states, res={}):
        if res == {}:
            res = {s: 0 for s in states_to_get}

        for purchase in self.purchases:
            state = purchase.state
            if state in states_to_get:
                res[state] += 1

        return res


class Price(db.Model):
    __tablename__ = "product_price"
    # Only allow 1 price per currency per price tier
    __table_args__ = (
        UniqueConstraint('price_tier_id', 'currency', name='_product_currency_uniq'),
    )

    id = db.Column(db.Integer, primary_key=True)
    price_tier_id = db.Column(db.Integer, db.ForeignKey("product_group.id"), nullable=False)
    currency = db.Column(db.String, nullable=False)
    price_int = db.Column(db.Integer, nullable=False)
    price_tier = db.relationship(PriceTier, backref=db.backref("prices", cascade="all"))

    @property
    def value(self):
        return Decimal(self.price_int) / 100

    @value.setter
    def value(self, val):
        self.price_int = int(val * 100)


class ProductInstance(db.Model):
    __versioned__ = {}
    __tablename__ = "product_instance"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    price_tier_id = db.Column(db.Integer, db.ForeignKey('product_group.id'), nullable=False)
    price_id = db.Column(db.Integer, db.ForeignKey('product_price.id'))

    # History
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow)

    # State tracking info
    state = db.Column(db.String, default='reserved', nullable=False)
    # Until a ticket is paid for, we track the payment's expiry
    expires = db.Column(db.DateTime, nullable=False)

    # Financial tracking
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))
    refund_id = db.Column(db.Integer, db.ForeignKey('refund.id'))

    # Relationships
    price = db.relationship(Price, backref='purchases')
    price_tier = db.relationship(PriceTier, backref='purchases')
    payment = db.relationship('Payment', backref='purchase')
    refund = db.relationship('Refund', backref='purchase')

    def __init__(self, **kwargs):
        expires = datetime.utcnow() + timedelta(hours=PRODUCT_INSTANCE_EXPIRY_TIME)
        super().__init__(expires=expires, **kwargs)

    def set_state(self, new_state):
        new_state = new_state.lower()

        if new_state not in PRODUCT_INSTANCE_STATES:
            raise ProductInstanceStateException('"%s" is not a valid state.')

        if new_state not in PRODUCT_INSTANCE_STATES[self.state]:
            raise ProductInstanceStateException('"%s->%s" is not a valid transition' % (self.state, new_state))

        self.state = new_state

    @classmethod
    def create_instances(self, user, tier, currency, count=1, token=''):
        try:
            price = [p for p in tier.prices if p.currency == currency.lower()][0]
        except IndexError:
            msg = 'Could not find currency, %s, for %s' % (currency, tier)
            raise ProductGroupException(msg)

        tier.issue_instances(count, token)

        return [ProductInstance(price_tier_id=tier.id,
                                user_id=user.id,
                                price_id=price.id,
                ) for c in range(count)]
