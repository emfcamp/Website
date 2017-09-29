# coding=utf-8
import sys
from decimal import Decimal
from datetime import datetime, timedelta

from main import db

from sqlalchemy import UniqueConstraint, and_, func
from sqlalchemy.orm import column_property

# state: [allowed next state, ] pairs
PRODUCT_INSTANCE_STATES = { 'reserved': ['payment-pending', 'expired'],
                            'payment-pending': ['expired', 'paid'],
                            'expired': [],
                            'paid': ['receipt-emailed', 'refunded'],
                            'receipt-emailed': ['checked-in', 'paid', 'refunded'],
                            'refunded': [],
                            # allow undoing of check-in
                            'checked-in': ['receipt-emailed', 'badged-up'],
                            'badged-up': ['checked-in'],
                            }
# non_blocking_states are those states that don't contribute towards a user limit
non_blocking_states = ('expired', 'refunded')
# These are the states that a product has to be in for admission
admission_states = ('receipt-emailed', 'checked-in', 'badged-up')
allowed_states = set(PRODUCT_INSTANCE_STATES.keys())

# In hours
PRODUCT_INSTANCE_EXPIRY_TIME = 2


class ProductInstanceStateException(Exception):
    pass

class ProductGroupException(Exception):
    pass

class CheckinStateException(Exception):
    pass

class ProductTransferException(Exception):
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

    # A max capacity of None implies no max (or use parent's if set)
    capacity_max = db.Column(db.Integer, default=None)
    capacity_used = db.Column(db.Integer, default=0)
    discount_token = db.Column(db.String)

    # Flags
    allow_check_in = db.Column(db.Boolean, default=None)
    allow_badge_up = db.Column(db.Boolean, default=None)
    is_visible = db.Column(db.Boolean, default=None)
    is_transferable = db.Column(db.Boolean, default=None)

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

        return count <= self.get_total_remaining_capacity()

    def remaining_capacity(self):
        """
        Return remaining capacity or sys.maxsize (a very big integer) if
        capacity_max is not set (i.e. None).
        """
        if self.capacity_max is None:
            return sys.maxsize
        return self.capacity_max - self.capacity_used

    def get_total_remaining_capacity(self):
        """
        Get the capacity remaining to this ProductGroup, and all its ancestors.

        Returns sys.maxsize if no ProductGroups have a capacity_max set.
        """
        remaining = [self.remaining_capacity()]
        if self.parent:
            remaining.append(self.parent.get_total_remaining_capacity())

        return min(remaining)

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

    def check_flag(self, flag):
        """
        Check whether this ProductGroup, or its ancestors, has a particular
        flag set.

        If a flag has a NULL value it is ignored.

        The 'closest' flag takes priority.

        If no ProductGroups in the tree have the flag then None is returned.
        """
        this_flag = getattr(self, flag)
        if this_flag is not None:
            return this_flag

        if self.parent:
            return self.parent.check_flag(flag)

        return None

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

    personal_limit = db.Column(db.Integer, default=10, nullable=False)

    def get_counts_by_state(self, states_to_get=allowed_states, res={}):
        if res == {}:
            res = {s: 0 for s in states_to_get}

        for purchase in self.purchases:
            state = purchase.state
            if state in states_to_get:
                res[state] += 1

        return res

    def user_limit(self, user, token=''):
        if self.has_expired():
            return 0

        if not self.token_correct(token):
            return 0

        if user.is_authenticated:
            # How many have been sold to this user
            user_count = ProductInstance.query.filter(
                ProductInstance.price_tier == self,
                ProductInstance.purchaser == user,
                ~ProductInstance.state.in_(non_blocking_states)
            ).count()
        else:
            user_count = 0

        return min(self.personal_limit - user_count, self.get_total_remaining_capacity())

    def check_flag(self, flag):
        res = super().check_flag(flag)
        if res is None:
            raise ProductGroupException('%s flag not set for %s' % (flag, self))
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

    # User FKs
    # Store the owner & purchaser so that we can calculate user_limits against
    # the former. We don't want to make it possible to buy over the
    # personal_limit of a product by transferring away purchases.
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    purchaser_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Product FKs.
    # We don't technically need to store the price tier as we can get it from
    # the price but most of the time we want the tier rather than the price and
    # this means we can easily swap currency without changing the tier.
    price_tier_id = db.Column(db.Integer, db.ForeignKey('product_group.id'), nullable=False)
    price_id = db.Column(db.Integer, db.ForeignKey('product_price.id'))

    # Financial FKs
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))
    refund_id = db.Column(db.Integer, db.ForeignKey('refund.id'))

    # History
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow)

    # State tracking info
    state = db.Column(db.String, default='reserved', nullable=False)
    # Until a ticket is paid for, we track the payment's expiry
    expires = db.Column(db.DateTime, nullable=False)

    # Relationships
    owner = db.relationship('User', backref='products', foreign_keys=[owner_id])
    purchaser = db.relationship('User', backref='purchases', foreign_keys=[purchaser_id])
    price = db.relationship(Price, backref='purchases')
    price_tier = db.relationship(PriceTier, backref='purchases')
    payment = db.relationship('Payment', backref='purchase')
    refund = db.relationship('Refund', backref='purchase')

    def __init__(self, **kwargs):
        expires = datetime.utcnow() + timedelta(hours=PRODUCT_INSTANCE_EXPIRY_TIME)
        super().__init__(expires=expires, **kwargs)

    def __repr__(self):
        if self.id is None:
            return "<ProductInstance -- %s: %s>" % (self.price_tier.name, self.state)
        return "<ProductInstance %s %s: %s>" % (self.id, self.price_tier.name, self.state)

    def check_in(self):
        if not self.price_tier.check_flag('allow_check_in'):
            raise ProductGroupException("Check-in not allowed with %s" % self.price_tier)

        if self.state == 'checked-in':
            raise CheckinStateException("Ticket is already checked in.")
        self.set_state('checked-in')

    def undo_check_in(self):
        if self.state != 'checked-in':
            raise CheckinStateException("Ticket is not checked in.")
        self.set_state('paid')

    def badge_up(self):
        if not self.price_tier.check_flag('allow_check_in'):
            raise ProductGroupException("Badge-up not allowed with %s" % self.price_tier)

        if self.state == 'badge-up':
            raise CheckinStateException("Ticket is already badged up.")
        self.set_state('badge-up')

    def undo_badge_up(self):
        if self.state != 'badge-up':
            raise CheckinStateException("Ticket is not badged up.")
        self.set_state('check-in')

    def allow_admission(self):
        return self.state in admission_states and self.price_tier.check_flag('allow_check_in')

    def set_state(self, new_state):
        new_state = new_state.lower()

        if new_state not in PRODUCT_INSTANCE_STATES:
            raise ProductInstanceStateException('"%s" is not a valid state.')

        if new_state not in PRODUCT_INSTANCE_STATES[self.state]:
            raise ProductInstanceStateException('"%s->%s" is not a valid transition' % (self.state, new_state))

        self.state = new_state

    def transfer(self, from_user, to_user, session):
        if not self.price_tier.check_flag('is_transferable'):
            raise ProductTransferException('This item is not transferable.')

        if self.owner != from_user:
            raise ProductTransferException('%s does not own this item' % from_user)

        # The ticket will need to be re-issued via email
        if self.state == 'receipt-emailed':
            self.set_state('paid')

        self.owner = to_user

        session.add(ProductTransfer(product_instance=self, to_user=to_user, from_user=from_user))
        session.commit()

    @classmethod
    def create_instances(self, user, tier, currency, count=1, token=''):
        try:
            price = [p for p in tier.prices if p.currency == currency.lower()][0]
        except IndexError:
            msg = 'Could not find currency, %s, for %s' % (currency, tier)
            raise ProductGroupException(msg)

        if count > tier.user_limit(user, token):
            raise ProductGroupException('Insufficient user capacity.')

        tier.issue_instances(count, token)

        return [ProductInstance(price_tier_id=tier.id,
                                owner_id=user.id,
                                purchaser_id=user.id,
                                price_id=price.id,
                ) for c in range(count)]

class ProductTransfer(db.Model):
    __tablename__ = 'product_transfer'
    id = db.Column(db.Integer, primary_key=True)
    product_instance_id = db.Column(db.Integer, db.ForeignKey('product_instance.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    product_instance = db.relationship(ProductInstance, backref=db.backref("transfers", cascade="all"))
    to_user = db.relationship('User', backref="to_transfers", foreign_keys=[to_user_id])
    from_user = db.relationship('User', backref="from_transfers", foreign_keys=[from_user_id])

    def __init__(self, product_instance, to_user, from_user):
        if to_user.id == from_user.id:
            raise ProductTransferException('"From" and "To" users must be different.')
        super().__init__(product_instance=product_instance, to_user=to_user, from_user=from_user)

    def __repr__(self):
        return "<Product Transfer: %s from %s to %s on %s>" % (
            self.ticket_id, self.from_user_id, self.to_user_id, self.timestamp)
