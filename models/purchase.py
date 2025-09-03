from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, func, select
from sqlalchemy.orm import Mapped, aliased, column_property, mapped_column, relationship, validates
from sqlalchemy_continuum.utils import transaction_class, version_class
from sqlalchemy_continuum.version import VersionClassBase

from main import db

from . import BaseModel, Currency, bucketise, export_attr_counts, export_intervals, naive_utcnow
from .user import User

if TYPE_CHECKING:
    from .payment import Payment, Refund, RefundRequest
    from .product import Price, PriceTier, Product

__all__ = [
    "AdmissionTicket",
    "CheckinStateException",
    "Purchase",
    "PurchaseStateException",
    "PurchaseTransfer",
    "PurchaseTransferException",
    "Ticket",
]

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

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column()
    is_ticket = column_property(type == "ticket" or type == "admission_ticket")

    # User FKs
    # Store the owner & purchaser separately so that we can track payment statistics
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), index=True)
    purchaser_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"), index=True)

    # Product FKs.
    # price_tier and product_id are denormalised for convenience.
    # We don't expect them to change, even if price_id does (by switching currency)
    price_id: Mapped[int] = mapped_column(ForeignKey("price.id"))
    price_tier_id: Mapped[int] = mapped_column(ForeignKey("price_tier.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))

    # Financial FKs
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payment.id"))
    refund_id: Mapped[int | None] = mapped_column(ForeignKey("refund.id"))
    refund_request_id: Mapped[int | None] = mapped_column(ForeignKey("refund_request.id"))

    # History
    created: Mapped[datetime] = mapped_column(default=naive_utcnow)
    modified: Mapped[datetime] = mapped_column(default=naive_utcnow, onupdate=naive_utcnow)

    # State tracking info
    state: Mapped[str] = mapped_column(default="reserved")
    is_paid_for = column_property(state.in_(bought_states))
    # Whether an e-ticket has been issued for this item
    ticket_issued: Mapped[bool] = mapped_column(default=False)
    # Whether this ticket has been checked-in/merch issued
    redeemed: Mapped[bool] = mapped_column(default=False)

    # Relationships
    owner: Mapped[User] = relationship(
        primaryjoin="Purchase.owner_id == User.id",
        back_populates="owned_purchases",
    )
    purchaser: Mapped[User] = relationship(
        primaryjoin="Purchase.purchaser_id == User.id",
        back_populates="purchases",
    )
    price: Mapped["Price"] = relationship("Price", back_populates="purchases")
    price_tier: Mapped["PriceTier"] = relationship("PriceTier", back_populates="purchases")
    product: Mapped["Product"] = relationship("Product", back_populates="purchases")
    payment: Mapped["Payment"] = relationship("Payment", back_populates="purchases")
    refund: Mapped["Refund | None"] = relationship(back_populates="purchases", cascade="all")
    refund_request: Mapped["RefundRequest | None"] = relationship(back_populates="purchases")
    transfers: Mapped[list["PurchaseTransfer"]] = relationship(back_populates="purchase", cascade="all")

    __mapper_args__ = {"polymorphic_on": "type", "polymorphic_identity": "purchase"}

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
            select(func.count(PurchaseTransfer.id)).select_from(cls).outerjoin(cls.transfers).group_by(cls.id)
        )

        cls_version = version_class(cls)
        cls_transaction = transaction_class(cls)
        changes = select(cls).join(cls.versions).group_by(cls.id)
        change_counts = changes.with_only_columns(func.count(cls_version.id))

        cls_ver_redeemed = aliased(cls_version)
        cls_txn_redeemed = aliased(cls_transaction)
        unredeemed_time = func.max(cls_txn_redeemed.issued_at) - cls.created
        unredeemed_times = (
            select(unredeemed_time.label("unredeemed_time"))
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
                        "created_week": export_intervals(select(cls), cls.created, "week", "YYYY-MM-DD"),
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
    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_id: Mapped[int] = mapped_column(ForeignKey("purchase.id"))
    to_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    from_user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    timestamp: Mapped[datetime] = mapped_column(default=naive_utcnow)

    purchase: Mapped[Purchase] = relationship(back_populates="transfers")
    to_user: Mapped[User] = relationship(back_populates="transfers_to", foreign_keys=[to_user_id])
    from_user: Mapped[User] = relationship(back_populates="transfers_from", foreign_keys=[from_user_id])

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
                        "timestamp_week": export_intervals(select(cls), cls.timestamp, "week", "YYYY-MM-DD"),
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
