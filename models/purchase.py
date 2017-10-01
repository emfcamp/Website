from datetime import datetime, timedelta
from sqlalchemy.orm import column_property
from main import db

# state: [allowed next state, ] pairs
PURCHASE_STATES = {'reserved': ['payment-pending', 'expired'],
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
bought_states = ('paid', ) + admission_states
allowed_states = set(PURCHASE_STATES.keys())
PURCHASE_EXPIRY_TIME = 2  # In hours


class CheckinStateException(Exception):
    pass


class Purchase(db.Model):
    """ A Purchase. This could be a ticket or an item of merchandise. """
    __versioned__ = {}

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String, nullable=False)

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
    price_tier_id = db.Column(db.Integer, db.ForeignKey('price_tier.id'), nullable=False)
    price_id = db.Column(db.Integer, db.ForeignKey('product_price.id'))

    # Financial FKs
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))
    refund_id = db.Column(db.Integer, db.ForeignKey('refund.id'))

    # History
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow)

    # State tracking info
    state = db.Column(db.String, default='reserved', nullable=False)
    # Until an instance is paid for, we track the payment's expiry
    expires = db.Column(db.DateTime, nullable=False)
    is_paid_for = column_property(state.in_(bought_states))

    # Relationships
    owner = db.relationship('User', backref='purchases', foreign_keys=[owner_id])
    purchaser = db.relationship('User', backref='purchased', foreign_keys=[purchaser_id])
    price = db.relationship('Price', backref='purchases')
    price_tier = db.relationship('PriceTier', backref='purchases')
    payment = db.relationship('Payment', backref='purchases')
    refund = db.relationship('Refund', backref='purchases')

    def __init__(self, price_tier, price, purchaser, owner, **kwargs):
        expires = datetime.utcnow() + timedelta(hours=PURCHASE_EXPIRY_TIME)

        super().__init__(price_tier=price_tier, price=price, purchaser=purchaser,
                         owner=owner, expires=expires, **kwargs)

    def __repr__(self):
        if self.id is None:
            return "<ProductInstance -- %s: %s>" % (self.price_tier.name, self.state)
        return "<ProductInstance %s %s: %s>" % (self.id, self.price_tier.name, self.state)

    @property
    def is_ticket(self):
        return self.type == 'ticket'

    def set_state(self, new_state):
        new_state = new_state.lower()

        if new_state not in PURCHASE_STATES:
            raise PurchaseStateException('"%s" is not a valid state.')

        if new_state not in PURCHASE_STATES[self.state]:
            raise PurchaseStateException('"%s->%s" is not a valid transition' % (self.state, new_state))

        self.state = new_state

    def transfer(self, from_user, to_user, session):
        if not self.price_tier.is_transferable:
            raise PurchaseTransferException('This item is not transferable.')

        if self.owner != from_user:
            raise PurchaseTransferException('%s does not own this item' % from_user)

        # The ticket will need to be re-issued via email
        if self.state == 'receipt-emailed':
            self.set_state('paid')

        self.owner = to_user

        session.add(PurchaseTransfer(product_instance=self, to_user=to_user, from_user=from_user))
        session.commit()

    @classmethod
    def create_instances(cls, user, tier, currency, count=1, token=''):
        price = tier.get_price(currency)

        if count > tier.user_limit(user, token):
            raise Exception('Insufficient user capacity.')

        tier.issue_instances(count, token)

        return [Purchase(tier, price, user, user) for c in range(count)]

    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'purchase'
    }


class Ticket(Purchase):
    __mapper_args__ = {
        'polymorphic_identity': 'ticket'
    }

    #  is_valid_ticket = column_property(super().state.in_(admission_states))

    def check_in(self):
        if not self.price_tier.allow_check_in:
            raise CheckinStateException("Check-in not allowed with %s" % self.price_tier)

        if self.state == 'checked-in':
            raise CheckinStateException("Ticket is already checked in.")
        self.set_state('checked-in')

    def undo_check_in(self):
        if self.state != 'checked-in':
            raise CheckinStateException("Ticket is not checked in.")
        self.set_state('paid')

    def badge_up(self):
        if not self.price_tier.allow_badge_up:
            raise CheckinStateException("Badge-up not allowed with %s" % self.price_tier)

        if self.state == 'badge-up':
            raise CheckinStateException("Ticket is already badged up.")
        self.set_state('badge-up')

    def undo_badge_up(self):
        if self.state != 'badge-up':
            raise CheckinStateException("Ticket is not badged up.")
        self.set_state('check-in')


class PurchaseTransfer(db.Model):
    """ A record of a purchase being transferred from one user to another. """
    __tablename__ = 'purchase_transfer'
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey('purchase.id'), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    product_instance = db.relationship(Purchase, backref=db.backref("transfers", cascade="all"))
    to_user = db.relationship('User', backref="transfers_to", foreign_keys=[to_user_id])
    from_user = db.relationship('User', backref="transfers_from", foreign_keys=[from_user_id])

    def __init__(self, product_instance, to_user, from_user):
        if to_user.id == from_user.id:
            raise PurchaseTransferException('"From" and "To" users must be different.')
        super().__init__(product_instance=product_instance, to_user=to_user, from_user=from_user)

    def __repr__(self):
        return "<Purchase Transfer: %s from %s to %s on %s>" % (
            self.ticket_id, self.from_user_id, self.to_user_id, self.timestamp)


class PurchaseStateException(Exception):
    pass


class PurchaseTransferException(Exception):
    pass

