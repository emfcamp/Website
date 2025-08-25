from datetime import timedelta

from sqlalchemy.orm import aliased, column_property, validates
from sqlalchemy_continuum.utils import transaction_class, version_class
from sqlalchemy_continuum.version import VersionClassBase

from main import db

from . import BaseModel, Currency, bucketise, export_attr_counts, export_intervals, naive_utcnow
from .user import User

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
    price_tier_id = db.Column(db.Integer, db.ForeignKey("price_tier.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)

    # Financial FKs
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"))
    refund_id = db.Column(db.Integer, db.ForeignKey("refund.id"))
    refund_request_id = db.Column(db.Integer, db.ForeignKey("refund_request.id"))

    # History
    created = db.Column(db.DateTime, default=naive_utcnow, nullable=False)
    modified = db.Column(db.DateTime, default=naive_utcnow, nullable=False, onupdate=naive_utcnow)

    # State tracking info
    state = db.Column(db.String, default="reserved", nullable=False)
    is_paid_for = column_property(state.in_(bought_states))
    # Whether an e-ticket has been issued for this item
    ticket_issued = db.Column(db.Boolean, default=False, nullable=False)
    # Whether this ticket has been checked-in/merch issued
    redeemed = db.Column(db.Boolean, default=False, nullable=False)

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
            raise PurchaseStateException(f"{state} is not a valid state for unclaimed purchases")

        super().__init__(
            price=price,
            price_tier=price.price_tier,
            product=price.price_tier.parent,
            purchaser=user,
            owner=user,
            state=state,
            **kwargs,
        )

    def __repr__(self):
        if self.id is None:
            return f"<Purchase -- {self.price_tier.name}: {self.state}>"
        return f"<Purchase {self.id} {self.price_tier.name}: {self.state}>"

    @property
    def is_transferable(self):
        return self.product.get_attribute("is_transferable") and not self.redeemed

    def is_refundable(self, ignore_event_refund_state=False) -> bool:
        return (
            (self.is_paid_for is True)
            and not self.is_transferred
            and self.payment.is_refundable(ignore_event_refund_state)
            and not self.redeemed
        )

    @property
    def is_transferred(self) -> bool:
        return self.owner_id != self.purchaser_id

    @validates("ticket_issued")
    def validate_ticket_issued(self, _key, issued):
        if not self.is_paid_for:
            raise PurchaseStateException("Ticket cannot be issued for a purchase which hasn't been paid for")
        return issued

    def set_user(self, user: User):
        if self.state != "reserved" or self.owner_id is not None or self.purchaser_id is not None:
            raise PurchaseStateException("Can only set state on purchases that are unclaimed & reserved.")

        if user is None:
            raise PurchaseStateException("Cannot unclaim a purchase.")

        self.owner_id = user.id
        self.purchaser_id = user.id

    def set_state(self, new_state):
        if new_state == self.state:
            return

        if new_state not in PURCHASE_STATES:
            raise PurchaseStateException(f'"{new_state}" is not a valid state.')

        if new_state not in PURCHASE_STATES[self.state]:
            raise PurchaseStateException(f'"{self.state}->{new_state}" is not a valid transition')

        if self.owner_id is None or self.purchaser_id is None:
            if new_state not in anon_states:
                raise PurchaseStateException(f"{new_state} is not a valid state for unclaimed purchases")

        self.state = new_state

    def cancel(self):
        if self.state == "cancelled":
            raise PurchaseStateException(f"{self} is already cancelled")

        if self.state in ["reserved", "admin-reserved", "payment-pending", "paid"]:
            self.price_tier.return_instances(1)

        self.set_state("cancelled")

    def refund_purchase(self, refund=None):
        if self.state == "refunded":
            raise PurchaseStateException(f"{self} is already refunded")

        if self.state in ["reserved", "admin-reserved", "payment-pending", "paid"]:
            self.price_tier.return_instances(1)

        self.state = "refunded"
        self.refund = refund

    def un_refund(self):
        if self.state != "refunded":
            raise PurchaseStateException(f"{self} is not refunded")

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
            raise PurchaseTransferException(f"{from_user} does not own this item")

        # The ticket will need to be re-issued via email
        self.ticket_issued = False
        self.owner = to_user

        transfer = PurchaseTransfer(purchase=self, to_user=to_user, from_user=from_user)
        db.session.add(transfer)

    def redeem(self):
        if not self.product.get_attribute("is_redeemable"):
            raise CheckinStateException("This item isn't redeemable.")
        if self.is_paid_for is False:
            raise CheckinStateException("Trying to redeem an item which hasn't been paid for.")
        if self.redeemed is True:
            raise CheckinStateException("Purchase has already been redeemed.")
        self.redeemed = True

    def unredeem(self):
        if not self.product.get_attribute("is_redeemable"):
            raise CheckinStateException("This item isn't redeemable.")
        if self.redeemed is False:
            raise CheckinStateException("Purchase hasn't been redeemed.")
        self.redeemed = False

    def redemption_version(self) -> VersionClassBase | None:
        if not self.redeemed:
            return None
        # This is inefficient without continuum's PropertyModTrackerPlugin
        # However: usually the only attribute that changes is the redemption bit
        for ver in self.versions[::-1]:
            if "redeemed" in ver.changeset:
                return ver
        return None

    @classmethod
    def get_export_data(cls):
        transfer_counts = (
            db.select(db.func.count(PurchaseTransfer.id))
            .select_from(cls)
            .outerjoin(cls.transfers)
            .group_by(cls.id)
        )

        cls_version = version_class(cls)
        cls_transaction = transaction_class(cls)
        changes = db.select(cls).join(cls.versions).group_by(cls.id)
        change_counts = changes.with_only_columns(db.func.count(cls_version.id))

        cls_ver_redeemed = aliased(cls_version)
        cls_txn_redeemed = aliased(cls_transaction)
        unredeemed_time = db.func.max(cls_txn_redeemed.issued_at) - cls.created
        unredeemed_times = (
            db.select(unredeemed_time.label("unredeemed_time"))
            .select_from(cls)
            .join(cls_ver_redeemed, cls_ver_redeemed.id == cls.id)
            .join(cls_txn_redeemed, cls_txn_redeemed.id == cls_ver_redeemed.transaction_id)
            .filter(cls_ver_redeemed.redeemed == True)
            .group_by(cls.id)
        )

        time_buckets = [timedelta(0), timedelta(minutes=1), timedelta(hours=1)] + [
            timedelta(d) for d in [1, 2, 3, 4, 5, 6, 7, 14, 1 * 28, 2 * 28, 3 * 28, 4 * 28, 5 * 28]
        ]

        data = {
            "public": {
                "purchases": {
                    "counts": {
                        "changes": bucketise(db.session.execute(change_counts), list(range(10)) + [10, 20]),
                        "created_week": export_intervals(db.select(cls), cls.created, "week", "YYYY-MM-DD"),
                        "transfers": bucketise(db.session.execute(transfer_counts), list(range(5)) + [5]),
                        "unredeemed_time": bucketise(
                            [r.unredeemed_time for r in db.session.execute(unredeemed_times)], time_buckets
                        ),
                    }
                }
            },
            "tables": ["purchase", "purchase_version"],
        }

        count_attrs = ["state", "redeemed"]
        data["public"]["purchases"]["counts"].update(export_attr_counts(cls, count_attrs))

        return data


class Ticket(Purchase):
    """A ticket, which is a specific type of purchase, but with different vocabulary.

    This can either be an admission ticket or a parking/camping ticket.
    """

    __mapper_args__ = {"polymorphic_identity": "ticket"}


class AdmissionTicket(Ticket):
    """A ticket that can contribute to the licensed capacity and be issued a badge."""

    __mapper_args__ = {"polymorphic_identity": "admission_ticket"}


class PurchaseTransfer(BaseModel):
    """A record of a purchase being transferred from one user to another."""

    __tablename__ = "purchase_transfer"
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchase.id"), nullable=False)
    to_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    from_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=naive_utcnow)

    purchase = db.relationship(Purchase, backref=db.backref("transfers", cascade="all"))

    def __init__(self, purchase, to_user, from_user):
        if to_user.id == from_user.id:
            raise PurchaseTransferException('"From" and "To" users must be different.')
        super().__init__(purchase=purchase, to_user_id=to_user.id, from_user_id=from_user.id)

    def __repr__(self):
        return f"<Purchase Transfer: {self.purchase_id} from {self.from_user_id} to {self.to_user_id} on {self.timestamp}>"

    @classmethod
    def get_export_data(cls):
        data = {
            "public": {
                "transfers": {
                    "counts": {
                        "timestamp_week": export_intervals(
                            db.select(cls), cls.timestamp, "week", "YYYY-MM-DD"
                        ),
                    }
                }
            },
            "tables": ["purchase_transfer"],
        }

        return data


class PurchaseStateException(Exception):
    pass


class PurchaseTransferException(Exception):
    pass
