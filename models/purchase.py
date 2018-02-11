from datetime import datetime
from sqlalchemy.orm import column_property
from main import db

# The type of a product determines how we handle it after purchase.
#
# Both `admission_ticket` and `parking_ticket` will generate a ticket,
# but only `admission_ticket` allows access to the site.
PRODUCT_TYPES = ["admission_ticket", "ticket", "merchandise"]

# state: [allowed next state, ] pairs, see docs/ticket_states.md
PURCHASE_STATES = {'reserved': ['payment-pending', 'expired', 'cancelled', 'paid'],
                   'payment-pending': ['expired', 'paid', 'cancelled'],
                   'expired': [],
                   'cancelled': [],
                   'paid': ['receipt-emailed', 'refunded'],
                   'receipt-emailed': ['paid', 'refunded'],
                   'refunded': [],
                   }
# non_blocking_states are those states that don't contribute towards a user limit
non_blocking_states = ('expired', 'refunded', 'cancelled')
bought_states = ('paid', 'receipt-emailed')
anon_states = ('reserved', 'cancelled', 'expired')
allowed_states = set(PURCHASE_STATES.keys())

class CheckinStateException(Exception):
    pass


class Purchase(db.Model):
    """ A Purchase. This could be a ticket or an item of merchandise. """
    __tablename__ = 'purchase'
    __versioned__ = {}

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String, nullable=False)
    is_ticket = column_property(type == 'ticket' or type == 'admission_ticket')

    # User FKs
    # Store the owner & purchaser separately so that we can track payment statistics
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    purchaser_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)

    # Product FKs.
    # price_tier and product_id are denormalised for convenience.
    # We don't expect them to change, even if price_id does (by switching currency)
    price_id = db.Column(db.Integer, db.ForeignKey('price.id'), nullable=False)
    price_tier_id = db.Column(db.Integer, db.ForeignKey('price_tier.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)

    # Financial FKs
    payment_id = db.Column(db.Integer, db.ForeignKey('payment.id'))
    refund_id = db.Column(db.Integer, db.ForeignKey('refund.id'))

    # History
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow)

    # State tracking info
    state = db.Column(db.String, default='reserved', nullable=False)
    is_paid_for = column_property(state.in_(bought_states))

    # Relationships
    price = db.relationship('Price', backref='purchases')
    price_tier = db.relationship('PriceTier')
    product = db.relationship('Product')

    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'purchase'
    }


    def __init__(self, price, user=None, state=None, **kwargs):
        if user is None and state is not None and state not in anon_states:
            raise PurchaseStateException('%s is not a valid state for unclaimed purchases' % state)

        super().__init__(price=price, price_tier=price.price_tier, product=price.price_tier.parent,
                         purchaser=user, owner=user, state=state, **kwargs)

    def __repr__(self):
        if self.id is None:
            return "<Purchase -- %s: %s>" % (self.price_tier.name, self.state)
        return "<Purchase %s %s: %s>" % (self.id, self.price_tier.name, self.state)

    @property
    def is_transferable(self):
        return self.price_tier.parent.get_attribute('is_transferable')

    def set_user(self, user):
        if self.state != 'reserved' or \
           self.owner_id is not None or \
           self.purchaser_id is not None:
            raise PurchaseStateException('Can only set state on purchases that are unclaimed & reserved.')

        if user is None:
            raise PurchaseStateException('Cannot unclaim a purchase.')

        self.owner_id = user.id
        self.purchaser_id = user.id

    def set_state(self, new_state):
        if new_state == self.state:
            return

        if new_state not in PURCHASE_STATES:
            raise PurchaseStateException('"%s" is not a valid state.')

        if new_state not in PURCHASE_STATES[self.state]:
            raise PurchaseStateException('"%s->%s" is not a valid transition' % (self.state, new_state))

        if self.owner_id is None or self.purchaser_id is None:
            if new_state not in anon_states:
                raise PurchaseStateException('%s is not a valid state for unclaimed purchases' % new_state)

        self.state = new_state

    def change_currency(self, currency):
        self.price = self.price_tier.get_price(currency)

    def transfer(self, from_user, to_user, session):
        if self.state not in bought_states:
            # We don't allow reserved items to be transferred to prevent a rush
            raise PurchaseTransferException('Only paid items may be transferred.')

        if not self.is_transferable:
            raise PurchaseTransferException('This item is not transferable.')

        if self.owner != from_user:
            raise PurchaseTransferException('%s does not own this item' % from_user)

        # The ticket will need to be re-issued via email
        if self.state == 'receipt-emailed':
            self.set_state('paid')

        self.owner = to_user

        session.add(PurchaseTransfer(purchase=self,
                                     to_user=to_user,
                                     from_user=from_user))


class Ticket(Purchase):
    """ A ticket, which is a specific type of purchase, but with different vocabulary.

        This can either be an admission ticket or a parking/camping ticket.
    """
    __mapper_args__ = {
        'polymorphic_identity': 'ticket'
    }


class AdmissionTicket(Ticket):
    """ A ticket that can contribute to the licensed capacity and be issued a badge. """
    checked_in = db.Column(db.Boolean, default=False)
    badge_issued = db.Column(db.Boolean, default=False)

    __mapper_args__ = {
        'polymorphic_identity': 'admission_ticket'
    }

    def check_in(self):
        if self.checked_in is True:
            raise CheckinStateException("Ticket is already checked in.")
        self.checked_in = True

    def undo_check_in(self):
        if self.checked_in is False:
            raise CheckinStateException("Ticket is not checked in.")
        self.checked_in = False

    def badge_up(self):
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

    purchase = db.relationship(Purchase, backref=db.backref("transfers", cascade="all"))

    def __init__(self, purchase, to_user, from_user):
        if to_user.id == from_user.id:
            raise PurchaseTransferException('"From" and "To" users must be different.')
        super().__init__(purchase=purchase,
                         to_user_id=to_user.id,
                         from_user_id=from_user.id)

    def __repr__(self):
        return "<Purchase Transfer: %s from %s to %s on %s>" % (
            self.ticket_id, self.from_user_id, self.to_user_id, self.timestamp)


class PurchaseStateException(Exception):
    pass


class PurchaseTransferException(Exception):
    pass

