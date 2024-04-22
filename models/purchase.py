from datetime import datetime
from sqlalchemy.orm import column_property, validates
from main import db
from .user import User
from . import BaseModel, Currency


# The type of a product determines how we handle it after purchase.
#
# Both `admission_ticket` and `parking_ticket` will generate a ticket,
# but only `admission_ticket` allows access to the site.
PRODUCT_TYPES = ["admission_ticket", "ticket", "merchandise"]

# state: [allowed next state, ] pairs
PURCHASE_STATES = {
    "reserved": ["payment-pending", "paid", "cancelled"],
    "admin-reserved": ["payment-pending", "paid", "cancelled"],
    "payment-pending": ["paid", "cancelled"],
    "cancelled": [],
    "paid": ["refunded", "cancelled", "refund-pending"],
    "refund-pending": ["paid", "refunded", "cancelled"],
    "refunded": [],
}

bought_states = {"paid"}
anon_states = {"reserved", "cancelled"}
allowed_states = set(PURCHASE_STATES.keys())


class CheckinStateException(Exception):
    pass


class Purchase(BaseModel):
    """A Purchase. This could be a ticket or an item of merchandise."""

    __tablename__ = "purchase"
    __versioned__ = {"exclude": ["is_ticket", "is_paid_for"]}

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String, nullable=False)
    is_ticket = column_property(type == "ticket" or type == "admission_ticket")

    # User FKs
    # Store the owner & purchaser separately so that we can track payment statistics
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)
    purchaser_id = db.Column(db.Integer, db.ForeignKey("user.id"), index=True)

    # Product FKs.
    # price_tier and product_id are denormalised for convenience.
    # We don't expect them to change, even if price_id does (by switching currency)
    price_id = db.Column(db.Integer, db.ForeignKey("price.id"), nullable=False)
    price_tier_id = db.Column(
        db.Integer, db.ForeignKey("price_tier.id"), nullable=False
    )
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)

    # Financial FKs
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"))
    refund_id = db.Column(db.Integer, db.ForeignKey("refund.id"))
    refund_request_id = db.Column(db.Integer, db.ForeignKey("refund_request.id"))

    # History
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow
    )

    # State tracking info
    state = db.Column(db.String, default="reserved", nullable=False)
    is_paid_for = column_property(state.in_(bought_states))
    # Whether an e-ticket has been issued for this item
    ticket_issued = db.Column(db.Boolean, default=False, nullable=False)

    # Relationships
    owner = db.relationship(
        "User",
        primaryjoin="Purchase.owner_id == User.id",
        back_populates="owned_purchases",
    )
    purchaser = db.relationship(
        "User",
        primaryjoin="Purchase.purchaser_id == User.id",
        back_populates="purchases",
    )
    price = db.relationship("Price", backref="purchases")
    price_tier = db.relationship("PriceTier", backref="purchases")
    product = db.relationship("Product", backref="purchases")

    __mapper_args__ = {"polymorphic_on": type, "polymorphic_identity": "purchase"}

    def __init__(self, price, user=None, state=None, **kwargs):
        if user is None and state is not None and state not in anon_states:
            raise PurchaseStateException(
                "%s is not a valid state for unclaimed purchases" % state
            )

        super().__init__(
            price=price,
            price_tier=price.price_tier,
            product=price.price_tier.parent,
            purchaser=user,
            owner=user,
            state=state,
            **kwargs
        )

    def __repr__(self):
        if self.id is None:
            return "<Purchase -- %s: %s>" % (self.price_tier.name, self.state)
        return "<Purchase %s %s: %s>" % (self.id, self.price_tier.name, self.state)

    @property
    def is_transferable(self):
        return self.product.get_attribute("is_transferable")

    def is_refundable(self, ignore_event_refund_state=False) -> bool:
        return (
            (self.is_paid_for is True)
            and not self.is_transferred
            and self.payment.is_refundable(ignore_event_refund_state)
        )

    @property
    def is_transferred(self) -> bool:
        return self.owner_id != self.purchaser_id

    @validates("ticket_issued")
    def validate_ticket_issued(self, _key, issued):
        if not self.is_paid_for:
            raise PurchaseStateException(
                "Ticket cannot be issued for a purchase which hasn't been paid for"
            )
        return issued

    def set_user(self, user: User):
        if (
            self.state != "reserved"
            or self.owner_id is not None
            or self.purchaser_id is not None
        ):
            raise PurchaseStateException(
                "Can only set state on purchases that are unclaimed & reserved."
            )

        if user is None:
            raise PurchaseStateException("Cannot unclaim a purchase.")

        self.owner_id = user.id
        self.purchaser_id = user.id

    def set_state(self, new_state):
        if new_state == self.state:
            return

        if new_state not in PURCHASE_STATES:
            raise PurchaseStateException('"%s" is not a valid state.' % new_state)

        if new_state not in PURCHASE_STATES[self.state]:
            raise PurchaseStateException(
                '"%s->%s" is not a valid transition' % (self.state, new_state)
            )

        if self.owner_id is None or self.purchaser_id is None:
            if new_state not in anon_states:
                raise PurchaseStateException(
                    "%s is not a valid state for unclaimed purchases" % new_state
                )

        self.state = new_state

    def cancel(self):
        if self.state == "cancelled":
            raise PurchaseStateException("{} is already cancelled".format(self))

        if self.state in ["reserved", "admin-reserved", "payment-pending", "paid"]:
            self.price_tier.return_instances(1)

        self.set_state("cancelled")

    def refund_purchase(self, refund=None):
        if self.state == "refunded":
            raise PurchaseStateException("{} is already refunded".format(self))

        if self.state in ["reserved", "admin-reserved", "payment-pending", "paid"]:
            self.price_tier.return_instances(1)

        self.state = "refunded"
        self.refund = refund

    def un_refund(self):
        if self.state != "refunded":
            raise PurchaseStateException("{} is not refunded".format(self))

        self.price_tier.issue_instances(1)
        self.state = "paid"
        self.refund = None

    def change_currency(self, currency: Currency):
        self.price = self.price_tier.get_price(currency)

    def transfer(self, from_user, to_user):
        if not self.is_paid_for:
            # We don't allow reserved items to be transferred to prevent a rush
            raise PurchaseTransferException("Only paid items may be transferred.")

        if not self.is_transferable:
            raise PurchaseTransferException("This item is not transferable.")

        if self.owner != from_user:
            raise PurchaseTransferException("%s does not own this item" % from_user)

        # The ticket will need to be re-issued via email
        self.ticket_issued = False
        self.owner = to_user

        PurchaseTransfer(purchase=self, to_user=to_user, from_user=from_user)


class Ticket(Purchase):
    """A ticket, which is a specific type of purchase, but with different vocabulary.

    This can either be an admission ticket or a parking/camping ticket.
    """

    __mapper_args__ = {"polymorphic_identity": "ticket"}


class AdmissionTicket(Ticket):
    """A ticket that can contribute to the licensed capacity and be issued a badge."""

    checked_in = db.Column(db.Boolean, default=False)
    badge_issued = db.Column(db.Boolean, default=False)

    __mapper_args__ = {"polymorphic_identity": "admission_ticket"}

    @property
    def is_transferable(self) -> bool:
        return self.product.get_attribute("is_transferable") and not self.checked_in

    def is_refundable(self, ignore_event_refund_state=False) -> bool:
        return super().is_refundable(ignore_event_refund_state) and not self.checked_in

    def check_in(self):
        if self.is_paid_for is False:
            raise CheckinStateException(
                "Trying to check in a ticket which hasn't been paid for."
            )
        if self.checked_in is True:
            raise CheckinStateException("Ticket is already checked in.")
        self.checked_in = True

    def undo_check_in(self):
        if self.checked_in is False:
            raise CheckinStateException("Ticket is not checked in.")
        self.checked_in = False

    def badge_up(self):
        if self.is_paid_for is False:
            raise CheckinStateException(
                "Trying to issue a badge for a ticket which hasn't been paid for."
            )
        if self.badge_issued is True:
            raise CheckinStateException("Ticket is already badged up.")
        self.badge_issued = True

    def undo_badge_up(self):
        if self.badge_issued is False:
            raise CheckinStateException("Ticket is not badged up.")
        self.badge_issued = False


class PurchaseTransfer(BaseModel):
    """A record of a purchase being transferred from one user to another."""

    __tablename__ = "purchase_transfer"
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchase.id"), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    purchase = db.relationship(Purchase, backref=db.backref("transfers", cascade="all"))

    def __init__(self, purchase, to_user, from_user):
        if to_user.id == from_user.id:
            raise PurchaseTransferException('"From" and "To" users must be different.')
        super().__init__(
            purchase=purchase, to_user_id=to_user.id, from_user_id=from_user.id
        )

    def __repr__(self):
        return "<Purchase Transfer: %s from %s to %s on %s>" % (
            self.purchase_id,
            self.from_user_id,
            self.to_user_id,
            self.timestamp,
        )


class PurchaseStateException(Exception):
    pass


class PurchaseTransferException(Exception):
    pass
