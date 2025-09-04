from __future__ import annotations

import logging
import random
import re
import string
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from sqlalchemy import ForeignKey, Numeric, UniqueConstraint, func, inspect, select
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import (
    Mapped,
    column_property,
    mapped_column,
    relationship,
    validates,
)

from main import NaiveDT, db
from models.user import User

from . import BaseModel, Currency, naive_utcnow
from .mixins import CapacityMixin, InheritedAttributesMixin
from .purchase import AdmissionTicket, Purchase, Ticket

if TYPE_CHECKING:
    # Imports used only in type hints, can't be imported normally due to circular references.
    from .arrivals import ArrivalsViewProduct
    from .basket import Basket
    from .payment import Payment

__all__ = [
    "MultipleLoadedResultsFound",
    "Price",
    "PriceTier",
    "Product",
    "ProductGroup",
    "ProductGroupException",
    "ProductGroupType",
    "ProductView",
    "ProductViewProduct",
    "Voucher",
    "VoucherUsedError",
]

log = logging.getLogger(__name__)


class ProductGroupException(Exception):
    pass


class MultipleLoadedResultsFound(Exception):
    pass


class VoucherUsedError(ValueError):
    pass


RANDOM_VOUCHER_LENGTH = 12

# Voucher expiry has a 36 hour grace period after the quoted expiry date, because the
# expiry date is 00:00 on the selected day and we want to make provision for different
# time zones.
VOUCHER_GRACE_PERIOD = timedelta(hours=36)


def random_voucher():
    return "".join(
        random.choices(
            list(set(string.ascii_lowercase) - {"a", "e", "i", "o", "u"} | set(string.digits)),
            k=RANDOM_VOUCHER_LENGTH,
        )
    )


def one_or_none[T](result: Sequence[T]) -> T | None:
    if len(result) == 1:
        return result[0]
    if len(result) == 0:
        return None
    raise MultipleLoadedResultsFound()


@dataclass(frozen=True)
class ProductGroupType:
    slug: str
    name: str
    purchase_cls: type[Purchase]


PRODUCT_GROUP_TYPES = [
    ProductGroupType("admissions", "Admission Ticket", AdmissionTicket),
    ProductGroupType("campervan", "Campervan Ticket", Ticket),
    ProductGroupType("parking", "Parking", Ticket),
    ProductGroupType("merchandise", "Merchandise", Purchase),
    ProductGroupType("rental", "Rental", Purchase),
    ProductGroupType("sponsorship", "Sponsorship", Purchase),
]
PRODUCT_GROUP_TYPES_DICT = {t.slug: t for t in PRODUCT_GROUP_TYPES}


class ProductGroup(BaseModel, CapacityMixin, InheritedAttributesMixin):
    """Represents a logical group of products.

    Capacity and attributes on a ProductGroup cascade down to the products within it.
    """

    __tablename__ = "product_group"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("product_group.id"))
    # Whether this is a ticket or hire item.
    type: Mapped[str]
    name: Mapped[str] = mapped_column(unique=True)

    products: Mapped[list[Product]] = relationship(
        back_populates="parent", cascade="all", order_by="Product.id"
    )
    parent: Mapped[ProductGroup | None] = relationship(back_populates="children", remote_side=[id])
    children: Mapped[list[ProductGroup]] = relationship(
        cascade="all",
        order_by=id,
    )

    def __init__(self, type=None, parent=None, parent_id=None, **kwargs):
        # XXX: Why are we specifying both parent and parent_id here?
        # Should also have mandatory argument for name.
        if type is None:
            if parent is None:
                type = ProductGroup.query.get(parent_id).type
            else:
                type = parent.type

        if type is None:
            raise ValueError("ProductGroup requires a type")

        super().__init__(type=type, parent=parent, parent_id=parent_id, **kwargs)

    @classmethod
    def get_by_name(cls, group_name: str) -> ProductGroup | None:
        return db.session.execute(
            select(ProductGroup).where(ProductGroup.name == group_name)
        ).scalar_one_or_none()

    @validates("capacity_max")
    def validate_capacity_max(self, _, capacity_max):
        """Validate the following rules for ProductGroup capacity on allocation-level
        ProductGroups:

        - If a parent ProductGroup has a max capacity set, either all child ProductGroups
            must have it set, or they must all be None.

        - The sum of child ProductGroup capacities cannot exceed the parent
            ProductGroup capacity.
        """

        if self.capacity_used is not None and capacity_max is not None and capacity_max < self.capacity_used:
            raise ValueError("capacity_max cannot be lower than capacity_used")

        with db.session.no_autoflush:
            # Disable autoflush in case we're in an initialiser
            if not self.parent or self.parent.capacity_max is None:
                return capacity_max

            siblings = list(self.parent.children)

        if self in siblings:
            siblings.remove(self)

        if capacity_max is None:
            if any(sibling.capacity_max for sibling in siblings):
                raise ValueError("capacity_max must be provided if siblings have capacity_max set.")
        else:
            if any(sibling.capacity_max is None for sibling in siblings):
                raise ValueError(
                    "One or more sibling ProductGroups has a None capacity. "
                    "This is a bug and you should fix that first."
                )

            sibling_capacity = sum(sibling.capacity_max for sibling in siblings)
            if sibling_capacity + capacity_max > self.parent.capacity_max:
                raise ValueError(
                    f"New capacity_max ({capacity_max}) + sum of sibling capacities ({sibling_capacity}) exceeds "
                    f"parent ProductGroup capacity ({self.parent.capacity_max})."
                )
        return capacity_max

    @property
    def unallocated_capacity(self) -> int | None:
        """If this is an allocation-level ProductGroup (i.e. it has a capacity_max
        set, and all childen also do), return the total unallocated capacity.

        Otherwise, return None.
        """

        if (
            self.capacity_max is None
            or len(self.children) == 0
            or any(child.capacity_max is None for child in self.children)
        ):
            return None

        # We check that all children have a non-None capacity_max above - but mypy isn't
        # able to infer this, hence the cast
        return self.capacity_max - sum(cast(int, child.capacity_max) for child in self.children)

    @property
    def purchase_count_by_state(self):
        states = defaultdict(int)

        for child in self.children:
            for k, v in child.purchase_count_by_state.items():
                states[k] += v

        for product in self.products:
            for k, v in product.purchase_count_by_state.items():
                states[k] += v

        return dict(**states)

    @classmethod
    def get_export_data(cls):
        def render_product(product):
            return {
                "name": product.name,
                "display_name": product.display_name,
                "description": product.description,
                "capacity_max": product.capacity_max,
                "capacity_used": product.capacity_used,
                "price_tiers": [
                    {
                        "name": tier.name,
                        "personal_limit": tier.personal_limit,
                        "active": tier.active,
                        "capacity_max": tier.capacity_max,
                        "capacity_used": tier.capacity_used,
                        "prices": [
                            {
                                "currency": price.currency,
                                "price_int": price.price_int,
                            }
                            for price in tier.prices
                        ],
                    }
                    for tier in product.price_tiers
                ],
            }

        def render_product_group(group):
            data = {
                "capacity_max": group.capacity_max,
                "capacity_used": group.capacity_used,
                "children": {},
                "products": [render_product(product) for product in group.products],
            }
            for child in group.children:
                data["children"][child.name] = render_product_group(child)
            return data

        data = {}
        root_groups = ProductGroup.query.filter_by(parent_id=None).all()
        for group in root_groups:
            data[group.name] = render_product_group(group)

        return {"private": data}

    def __repr__(self):
        return f"<{self.__class__.__name__}: {self.name}>"

    def __str__(self):
        return self.name


class Product(BaseModel, CapacityMixin, InheritedAttributesMixin):
    """A product (ticket or other item) which is for sale."""

    __tablename__ = "product"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey(ProductGroup.id))
    name: Mapped[str]
    display_name: Mapped[str | None]
    description: Mapped[str | None]

    price_tiers: Mapped[list[PriceTier]] = relationship(
        back_populates="parent", cascade="all", order_by="PriceTier.id"
    )
    product_view_products: Mapped[list[ProductViewProduct]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    arrivals_view_products: Mapped[list[ArrivalsViewProduct]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    purchases: Mapped[list[Purchase]] = relationship(back_populates="product")
    parent: Mapped[ProductGroup] = relationship(back_populates="products")

    __table_args__ = (UniqueConstraint("name", "group_id"),)
    __export_data__ = False  # Exported by ProductGroup

    @classmethod
    def get_by_name(cls, group_name: str, product_name: str) -> Product | None:
        return db.session.execute(
            select(ProductGroup)
            .where(ProductGroup.name == group_name)
            .join(Product)
            .where(Product.name == product_name)
            .with_only_columns(Product)
        ).scalar_one_or_none()

    @property
    def purchase_count_by_state(self) -> dict[str, int]:
        states = (
            db.session.execute(
                select(Purchase.state, func.count(Purchase.id))
                .join(PriceTier)
                .join(Product)
                .where(Product.id == self.id)
                .group_by(Purchase.state)
            )
            .tuples()
            .all()
        )

        return dict(states)

    def get_cheapest_price(self, currency: Currency = Currency.GBP) -> Price | None:
        price = (
            db.session.execute(
                select(PriceTier)
                .where(PriceTier.product_id == self.id)
                .join(Price)
                .where(Price.currency == currency)
                .with_only_columns(Price)
                .order_by(Price.price_int)
            )
            .scalars()
            .first()
        )
        return price

    def is_adult_ticket(self) -> bool:
        """Whether this is an "adult" ticket.

        This is used for two purposes:
            * Voucher capacity is only decremented by adult tickets
            * At least one adult ticket is needed in order to purchase other types of ticket.

        We have to consider under-18 tickets as adult tickets because 16-18 year olds may attend
        the event without an adult.

        Day tickets should be able to buy badges/merchandise.
        """
        # FIXME: Make this less awful, we need a less brittle way of detecting this
        return self.parent.type == "admissions" and (
            self.name.startswith("full") or self.name.startswith("u18") or self.name.startswith("day")
        )

    @property
    def checkin_display_name(self):
        if self.parent.type != "admissions":
            return self.display_name
        return re.sub(r" \(.*\)", "", self.display_name)

    def get_price_tier(self, name):
        tier = PriceTier.query.filter_by(product_id=self.id).filter_by(name=name)
        return tier.one_or_none()

    def __repr__(self):
        return f"<Product: {self.name}>"

    def __str__(self):
        return self.name


class PriceTier(BaseModel, CapacityMixin):
    """A pricing level for a Product.

    PriceTiers have a capacity and an expiry through the CapacityMixin.
    They have one Price object per currency.

    In theory PriceTiers could cascade based on price, but this is problematic
    with popular products as we need to update the customer each time.
    For now, only one PriceTier is active (unexpired) per Product at once.
    """

    __tablename__ = "price_tier"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    product_id: Mapped[int] = mapped_column(ForeignKey(Product.id))

    personal_limit: Mapped[int] = mapped_column(default=10)
    active: Mapped[bool] = mapped_column(default=True)
    vat_rate: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))

    __table_args__ = (UniqueConstraint("name", "product_id"),)
    __export_data__ = False  # Exported by ProductGroup

    prices: Mapped[list[Price]] = relationship(
        back_populates="price_tier", cascade="all", order_by="Price.id"
    )
    purchases: Mapped[list[Purchase]] = relationship(back_populates="price_tier")
    parent: Mapped[Product] = relationship(back_populates="price_tiers")

    def __init__(self, name=None, **kwargs):
        super().__init__(name=name, **kwargs)

    @classmethod
    def get_by_name(cls, group_name: str, product_name: str, tier_name: str) -> PriceTier | None:
        return db.session.execute(
            select(ProductGroup)
            .where(ProductGroup.name == group_name)
            .join(Product)
            .where(Product.name == product_name)
            .join(PriceTier)
            .where(PriceTier.name == tier_name)
            .with_only_columns(PriceTier)
        ).scalar_one_or_none()

    @property
    def purchase_count_by_state(self) -> dict[str, int]:
        states = (
            db.session.execute(
                select(Purchase.state, func.count(Purchase.id))
                .join(PriceTier)
                .where(PriceTier.id == self.id)
                .group_by(Purchase.state)
            )
            .tuples()
            .all()
        )

        return dict(states)

    @property
    def purchase_count(self) -> int:
        return db.session.execute(
            select(func.count()).select_from(Purchase).join(PriceTier).where(PriceTier.id == self.id)
        ).scalar_one()

    @property
    def unused(self) -> bool:
        """Whether this tier is unused and can be safely deleted."""
        return self.purchase_count == 0 and not self.active

    def get_price(self, currency: Currency) -> Price | None:
        instance_state = inspect(self)
        if "prices" in instance_state.unloaded:
            return self.get_price_unloaded(currency)
        return self.get_price_loaded(currency)

    def get_price_unloaded(self, currency: Currency) -> Price | None:
        return db.session.execute(
            select(Price).where(Price.price_tier_id == self.id, Price.currency == currency)
        ).scalar_one_or_none()

    def get_price_loaded(self, currency: Currency) -> Price | None:
        prices = [p for p in self.prices if p.currency == currency]
        return one_or_none(prices)

    def user_limit(self) -> int:
        if self.has_expired():
            return 0

        return min(self.personal_limit, self.get_total_remaining_capacity())

    def __repr__(self):
        return f"<PriceTier {self.name}>"

    def __str__(self):
        return self.name

    def __lt__(self, other):
        # This is apparently used by jinja's groupby filter
        return self.id < other.id


class Price(BaseModel):
    """Represents the price of a product, at a given price tier, in a given currency.

    Prices are immutable and should not be changed. We expire the PriceTier instead.
    """

    __tablename__ = "price"
    __export_data__ = False  # Exported by ProductGroup

    id: Mapped[int] = mapped_column(primary_key=True)
    price_tier_id: Mapped[int] = mapped_column(ForeignKey("price_tier.id"))
    currency: Mapped[Currency]
    price_int: Mapped[int]

    purchases: Mapped[list[Purchase]] = relationship(back_populates="price")
    price_tier: Mapped[list[PriceTier]] = relationship(back_populates="prices")

    def __init__(self, currency, value=None, **kwargs):
        super().__init__(currency=currency.upper(), **kwargs)
        if value is not None:
            self.value = value

    @property
    def value(self):
        return Decimal(self.price_int) / 100

    @value.setter
    def value(self, val):
        self.price_int = int(val * 100)

    @property
    def value_ex_vat(self):
        if self.price_tier.vat_rate is None:
            return self.value
        return self.value / (self.price_tier.vat_rate + 1)

    @value_ex_vat.setter
    def value_ex_vat(self, val):
        if self.price_tier.vat_rate is None:
            self.value = val
            return
        self.value = val * (self.price_tier.vat_rate + 1)

    @property
    def vat(self):
        if self.price_tier.vat_rate is None:
            return 0
        return self.value_ex_vat * self.price_tier.vat_rate

    def __repr__(self):
        return f"<Price for {self.price_tier!r}: {self.value:.2f} {self.currency}>"

    def __str__(self):
        return f"{self.value:0.2f} {self.currency}"


class Voucher(BaseModel):
    """A short code which allows a user to access a restricted ProductView"""

    __tablename__ = "voucher"
    __export_data__ = False  # Exported by ProductView

    code: Mapped[str] = mapped_column(primary_key=True)
    expiry: Mapped[NaiveDT | None]

    email: Mapped[str | None] = mapped_column(index=True)

    product_view_id: Mapped[int | None] = mapped_column(ForeignKey("product_view.id"))

    # The number of purchases remaining on this voucher
    purchases_remaining: Mapped[int] = mapped_column(default=1)

    # The number of adult tickets remaining to purchase on this voucher
    tickets_remaining: Mapped[int] = mapped_column(default=2)

    payment: Mapped[list[Payment]] = relationship(back_populates="voucher")
    view: Mapped[ProductView | None] = relationship(back_populates="vouchers")

    is_used = column_property((purchases_remaining == 0) | (tickets_remaining == 0))

    @classmethod
    def get_by_code(cls, code: str) -> Voucher | None:
        if not code:
            return None
        return db.session.execute(select(Voucher).where(Voucher.code == code)).scalar_one_or_none()

    def __init__(
        self,
        view: ProductView,
        code: str | None = None,
        expiry: NaiveDT | None = None,
        email: str | None = None,
        purchases_remaining: int = 1,
        tickets_remaining: int = 2,
    ):
        super().__init__()
        self.view = view
        self.email = email
        self.purchases_remaining = purchases_remaining
        self.tickets_remaining = tickets_remaining
        self.expiry = expiry

        # Creation may fail if code has already been used. This isn't ideal
        # but a 12 ascii character random string is unlikely to clash and
        # selected codes will need to be done with care.
        if code:
            self.code = code
        else:
            self.code = random_voucher()

    @property
    def is_expired(self) -> bool:
        # Note: this should be a column_property but getting the current time in the DB
        # interacts badly with the fact that we fake the date in tests.
        return self.expiry is not None and (self.expiry + VOUCHER_GRACE_PERIOD) < naive_utcnow()

    def check_capacity(self, basket: Basket) -> bool:
        """Check if there is enough capacity in this voucher to buy
        the tickets in the provided basket.
        """
        if self.purchases_remaining < 1:
            return False

        adult_tickets = sum(line.count for line in basket._lines if line.tier.parent.is_adult_ticket())

        if self.tickets_remaining < adult_tickets:
            return False
        return True

    def consume_capacity(self, payment: Payment) -> None:
        """Decrease the voucher's capacity based on tickets in a payment."""
        if self.purchases_remaining < 1:
            raise VoucherUsedError(f"Attempting to use voucher with no remaining purchases: {self}")

        adult_tickets = len(
            [purchase for purchase in payment.purchases if purchase.product.is_adult_ticket()]
        )

        if self.tickets_remaining < adult_tickets:
            raise VoucherUsedError(
                f"Attempting to purchase more adult tickets than allowed by voucher: {self}"
            )

        log.info("Consuming 1 purchase and %s tickets from %s", adult_tickets, self)
        self.purchases_remaining = Voucher.purchases_remaining - 1
        self.tickets_remaining = Voucher.tickets_remaining - adult_tickets

    def return_capacity(self, payment: Payment) -> None:
        """Return capacity to this voucher based on tickets in a payment."""
        adult_tickets = len(
            [purchase for purchase in payment.purchases if purchase.product.is_adult_ticket()]
        )
        log.info("Returning 1 purchase and %s tickets to %s", adult_tickets, self)
        self.purchases_remaining = Voucher.purchases_remaining + 1
        self.tickets_remaining = Voucher.tickets_remaining + adult_tickets

    def __repr__(self):
        if self.expiry:
            return f"<Voucher: {self.code}, view: {self.product_view_id}, expiry: {self.expiry}>"
        return f"<Voucher: {self.code}, view: {self.product_view_id}>"

    def is_accessible(self, voucher: str) -> bool:
        # voucher expired
        if self.is_expired:
            return False

        if self.code != voucher:
            return False

        if self.is_used:
            return False

        return True


class ProductView(BaseModel):
    """A selection of products to be shown together for sale."""

    __tablename__ = "product_view"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str]
    name: Mapped[str] = mapped_column(index=True)

    # Whether this productview is only accessible to users with an accepted CfP proposal
    cfp_accepted_only: Mapped[bool] = mapped_column(default=False)

    # Whether this productview is only accessible with a voucher associated with this productview
    vouchers_only: Mapped[bool] = mapped_column(default=False)

    product_view_products: Mapped[list[ProductViewProduct]] = relationship(
        back_populates="view",
        order_by="ProductViewProduct.order",
        cascade="all, delete-orphan",
    )

    vouchers: Mapped[list[Voucher]] = relationship(
        back_populates="view", cascade="all, delete-orphan", lazy=True
    )

    products = association_proxy("product_view_products", "product")

    @classmethod
    def get_export_data(cls):
        data = {}
        for view in ProductView.query.all():
            data[view.name] = {
                "name": view.name,
                "type": view.type,
                "products": [product.name for product in view.products],
                "cfp_accepted_only": view.cfp_accepted_only,
                "vouchers_only": view.vouchers_only,
                "voucher_count": len(view.vouchers),
            }
        return {"private": data}

    @classmethod
    def get_by_name(cls, name: str) -> ProductView | None:
        return db.session.execute(select(ProductView).where(ProductView.name == name)).scalar_one_or_none()

    def is_accessible_at(self, user: User, voucher: str | None = None) -> bool:
        "Whether this ProductView is accessible to a user."
        if user.is_authenticated and user.has_permission("admin"):
            # Admins always have access
            return True

        # CfP voucher
        if self.cfp_accepted_only:
            if user and user.is_authenticated and user.is_cfp_accepted:
                return True
            return False

        if self.vouchers_only:
            if not voucher:
                return False

            voucher_obj = db.session.execute(
                select(Voucher).where(Voucher.view == self, Voucher.code == voucher)
            ).scalar_one_or_none()

            if not voucher_obj:
                return False

            return voucher_obj.is_accessible(voucher)

        return True

    def is_accessible(self, user, voucher=None):
        return self.is_accessible_at(user, voucher=voucher)

    def __repr__(self):
        return f"<ProductView: {self.name}>"

    def __str__(self):
        return self.name


class ProductViewProduct(BaseModel):
    __tablename__ = "product_view_product"
    __export_data__ = False  # Exported by ProductView

    view_id: Mapped[int] = mapped_column(ForeignKey(ProductView.id), primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey(Product.id), primary_key=True)

    order: Mapped[int] = mapped_column(default=0)

    view: Mapped[ProductView] = relationship(back_populates="product_view_products")
    product: Mapped[Product] = relationship(back_populates="product_view_products")

    def __init__(self, view, product, order=None):
        self.view = view
        self.product = product
        if order is not None:
            self.order = order

    def __repr__(self):
        return f"<ProductViewProduct: view {self.view_id}, product {self.product_id}, order {self.order}>"
