from datetime import datetime, timedelta
from sqlalchemy.orm import column_property
from main import db
from .exc import CapacityException

# The type of a product determines how we handle it after purchase.
#
# Both `admission_ticket` and `parking_ticket` will generate a ticket,
# but only `admission_ticket` allows access to the site.
PRODUCT_TYPES = ["admission_ticket", "parking_ticket", "merchandise"]

# state: [allowed next state, ] pairs
PURCHASE_STATES = {'reserved': ['payment-pending', 'expired'],
                            'payment-pending': ['expired', 'paid'],
                            'expired': [],
                            'paid': ['receipt-emailed', 'refunded'],
                            'receipt-emailed': ['paid', 'refunded'],
                            'refunded': [],
                   }
# non_blocking_states are those states that don't contribute towards a user limit
non_blocking_states = ('expired', 'refunded')
bought_states = ('paid', 'receipt-emailed')
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
    price = db.relationship('Price', backref='purchases')
    price_tier = db.relationship('PriceTier', backref='purchases')

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

    @property
    def is_paid(self):
        return self.state in bought_states

    def set_state(self, new_state):
        new_state = new_state.lower()

        if new_state not in PURCHASE_STATES:
            raise PurchaseStateException('"%s" is not a valid state.')

        if new_state not in PURCHASE_STATES[self.state]:
            raise PurchaseStateException('"%s->%s" is not a valid transition' % (self.state, new_state))

        self.state = new_state

    def change_currency(self, currency):
        raise Exception("you wish.")

    def transfer(self, from_user, to_user, session):
        # TODO it'd be cool if you could transfer an allow someone else to pay
        if self.state not in bought_states:
            raise PurchaseTransferException('Only paid items may be transferred.')

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
    def class_from_product(cls, product):
        """ Return the class of purchase used for the given Product.

            Raises an exception if the purchase has no type.
        """
        product_type = product.get_type()
        if product_type is None:
            raise Exception("Product %s has no type" % (product))

        if product_type in ['admission_ticket', 'parking_ticket']:
            return Ticket
        else:
            return Purchase

    @classmethod
    def safe_create_instances(cls, session, user, items, currency):
        """ Transactionally issue products.

            Item should be a list of (PriceTier, count) pairs.
        """
        try:
            res = []
            for tier, count in items:
                # Session is passed in so that we can check capacity with
                # SELECT FOR UPDATE
                res += cls.create_instances(session, user, tier, currency, count)
            session.commit()
            return res
        except:
            session.rollback()
            raise

    @classmethod
    def create_instances(cls, session, user, tier, currency, count=1):
        """ Generate a number of Purchases when given a PriceTier.

            This ensures that capacity is available, and instantiates
            the correct Purchase type, returning a list of Purchases.
        """
        price = tier.get_price_object(currency)

        if count > tier.user_limit(user):
            raise CapacityException('Insufficient user capacity.')

        purchase_cls = cls.class_from_product(tier.parent)

        # TODO: This is the critical bit for ticket-buying race conditions.
        # As we're not doing a commit here, everything is in the current
        # transaction which the caller must commit. We might want to issue
        # a SELECT FOR UPDATE at this point to acquire locks on the
        # appropriate capacity counters.
        tier.issue_instances(session, count)

        return [purchase_cls(tier, price, user, user) for c in range(count)]

    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'purchase'
    }


class Ticket(Purchase):
    """ A ticket, which is a specific type of purchase.

        This can either be an admission ticket or a parking ticket.
    """
    __mapper_args__ = {
        'polymorphic_identity': 'ticket'
    }

    checked_in = db.Column(db.Boolean, default=False)
    badge_issued = db.Column(db.Boolean, default=False)

    def get_ticket_type(self):
        """ Return the type of this ticket: 'admission' or 'parking' """
        product_type = self.price_tier.parent.get_type()
        if product_type == 'admission_ticket':
            return 'admission'
        elif product_type == 'parking_ticket':
            return 'parking'

    def check_in(self):
        ticket_type = self.get_ticket_type()
        if ticket_type != 'admission':
            raise CheckinStateException("Check-in not allowed with %s ticket" % ticket_type)

        if self.checked_in is True:
            raise CheckinStateException("Ticket is already checked in.")

        self.checked_in = True

    def undo_check_in(self):
        if self.checked_in is False:
            raise CheckinStateException("Ticket is not checked in.")
        self.checked_in = False

    def badge_up(self):
        ticket_type = self.get_ticket_type()
        if ticket_type != 'admission':
            raise CheckinStateException("Badge-up not allowed with %s" % ticket_type)

        if self.badge_issued is True:
            raise CheckinStateException("Ticket is already badged up.")
        self.badge_issued = True

    def undo_badge_up(self):
        if self.badge_issued is False:
            raise CheckinStateException("Ticket is not badged up.")
        self.badge_issued = True


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

