from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from collections import defaultdict
from datetime import datetime, timedelta
import logging
import re
import random
import string
from typing import Optional, TYPE_CHECKING

from sqlalchemy import func, UniqueConstraint, inspect
from sqlalchemy.orm import validates, column_property
from sqlalchemy.ext.associationproxy import association_proxy

from main import db
from .mixins import CapacityMixin, InheritedAttributesMixin
from . import BaseModel
from .purchase import Purchase, AdmissionTicket, Ticket
from .payment import Currency

if TYPE_CHECKING:
    # Imports used only in type hints, can't be imported normally due to circular references.
    from .basket import Basket
    from .payment import Payment

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
            list(
                set(string.ascii_lowercase) - {"a", "e", "i", "o", "u"}
                | set(string.digits)
            ),
            k=RANDOM_VOUCHER_LENGTH,
        )
    )


def one_or_none(result):
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

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("product_group.id"))
    # Whether this is a ticket or hire item.
    type = db.Column(db.String, nullable=False)
    name = db.Column(db.String, unique=True, nullable=False)

    products = db.relationship(
        "Product", backref="parent", cascade="all", order_by="Product.id"
    )
    children = db.relationship(
        "ProductGroup",
        backref=db.backref("parent", remote_side=[id]),
        cascade="all",
        order_by="ProductGroup.id",
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
    def get_by_name(cls, group_name) -> Optional[ProductGroup]:
        return ProductGroup.query.filter_by(name=group_name).one_or_none()

    @validates("capacity_max")
    def validate_capacity_max(self, _, capacity_max):
        """Validate the following rules for ProductGroup capacity on allocation-level
        ProductGroups:

        - If a parent ProductGroup has a max capacity set, either all child ProductGroups
            must have it set, or they must all be None.

        - The sum of child ProductGroup capacities cannot exceed the parent
            ProductGroup capacity.
        """

        if (
            self.capacity_used is not None
            and capacity_max is not None
            and capacity_max < self.capacity_used
        ):
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
                raise ValueError(
                    "capacity_max must be provided if siblings have capacity_max set."
                )
        else:
            if any(sibling.capacity_max is None for sibling in siblings):
                raise ValueError(
                    "One or more sibling ProductGroups has a None capacity. "
                    "This is a bug and you should fix that first."
                )

            sibling_capacity = sum(sibling.capacity_max for sibling in siblings)
            if sibling_capacity + capacity_max > self.parent.capacity_max:
                raise ValueError(
                    "New capacity_max (%s) + sum of sibling capacities (%s) exceeds "
                    "parent ProductGroup capacity (%s)."
                    % (capacity_max, sibling_capacity, self.parent.capacity_max)
                )
        return capacity_max

    @property
    def unallocated_capacity(self) -> Optional[int]:
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

        return self.capacity_max - sum(child.capacity_max for child in self.children)

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
        return "<%s: %s>" % (self.__class__.__name__, self.name)

    def __str__(self):
        return self.name


class Product(BaseModel, CapacityMixin, InheritedAttributesMixin):
    """A product (ticket or other item) which is for sale."""

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey(ProductGroup.id), nullable=False)
    name = db.Column(db.String, nullable=False)
    display_name = db.Column(db.String)
    description = db.Column(db.String)
    price_tiers = db.relationship(
        "PriceTier", backref="parent", cascade="all", order_by="PriceTier.id"
    )
    product_view_products = db.relationship(
        "ProductViewProduct", backref="product", cascade="all, delete-orphan"
    )

    __table_args__ = (UniqueConstraint("name", "group_id"),)
    __export_data__ = False  # Exported by ProductGroup

    @classmethod
    def get_by_name(cls, group_name, product_name) -> Optional[Product]:
        group = ProductGroup.query.filter_by(name=group_name)
        product = (
            group.join(Product).filter_by(name=product_name).with_entities(Product)
        )
        return product.one_or_none()

    @property
    def purchase_count_by_state(self):
        states = (
            Purchase.query.join(PriceTier, Product)
            .filter(Product.id == self.id)
            .with_entities(Purchase.state, func.count(Purchase.id))
            .group_by(Purchase.state)
        )

        return dict(states)

    def get_cheapest_price(self, currency="GBP") -> "Price":
        price = (
            PriceTier.query.filter_by(product_id=self.id)
            .join(Price)
            .filter_by(currency=currency)
            .with_entities(Price)
            .order_by(Price.price_int)
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
        """
        # FIXME: Make this less awful, we need a less brittle way of detecting this
        return self.parent.type == "admissions" and (
            self.name.startswith("full") or self.name.startswith("u18")
        )

    @property
    def checkin_display_name(self):
        return re.sub(r" \(.*\)", "", self.display_name)

    def get_price_tier(self, name):
        tier = PriceTier.query.filter_by(product_id=self.id).filter_by(name=name)
        return tier.one_or_none()

    def __repr__(self):
        return "<Product: %s>" % self.name

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

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey(Product.id), nullable=False)

    personal_limit = db.Column(db.Integer, default=10, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    vat_rate = db.Column(db.Numeric(4, 3), nullable=True)

    __table_args__ = (UniqueConstraint("name", "product_id"),)
    __export_data__ = False  # Exported by ProductGroup

    prices = db.relationship(
        "Price", backref="price_tier", cascade="all", order_by="Price.id"
    )

    def __init__(self, name=None, **kwargs):
        super().__init__(name=name, **kwargs)

    @classmethod
    def get_by_name(cls, group_name, product_name, tier_name) -> Optional[PriceTier]:
        group = ProductGroup.query.filter_by(name=group_name)
        product = (
            group.join(Product).filter_by(name=product_name).with_entities(Product)
        )
        tier = (
            product.join(PriceTier).filter_by(name=tier_name).with_entities(PriceTier)
        )
        return tier.one_or_none()

    @property
    def purchase_count_by_state(self):
        states = (
            Purchase.query.join(PriceTier)
            .filter(PriceTier.id == self.id)
            .with_entities(Purchase.state, func.count(Purchase.id))
            .group_by(Purchase.state)
        )

        return dict(states)

    @property
    def purchase_count(self) -> int:
        return Purchase.query.join(PriceTier).filter(PriceTier.id == self.id).count()

    @property
    def unused(self) -> bool:
        """Whether this tier is unused and can be safely deleted."""
        return self.purchase_count == 0 and not self.active

    def get_price(self, currency: Currency) -> Optional["Price"]:
        if "prices" in inspect(self).unloaded:
            return self.get_price_unloaded(currency)
        else:
            return self.get_price_loaded(currency)

    def get_price_unloaded(self, currency: Currency) -> Optional[Price]:
        price = Price.query.filter_by(price_tier_id=self.id, currency=currency)
        return price.one_or_none()

    def get_price_loaded(self, currency: Currency) -> Optional[Price]:
        prices = [p for p in self.prices if p.currency == currency]
        return one_or_none(prices)

    def user_limit(self) -> int:
        if self.has_expired():
            return 0

        return min(self.personal_limit, self.get_total_remaining_capacity())

    def __repr__(self):
        return "<PriceTier %s>" % self.name

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

    id = db.Column(db.Integer, primary_key=True)
    price_tier_id = db.Column(
        db.Integer, db.ForeignKey("price_tier.id"), nullable=False
    )
    currency: Currency = db.Column(db.String, nullable=False)
    price_int = db.Column(db.Integer, nullable=False)

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
        return "<Price for %r: %.2f %s>" % (self.price_tier, self.value, self.currency)

    def __str__(self):
        return "%0.2f %s" % (self.value, self.currency)


class Voucher(BaseModel):
    """A short code which allows a user to access a restricted ProductView"""

    __tablename__ = "voucher"
    __export_data__ = False  # Exported by ProductView

    code = db.Column(db.String, primary_key=True)
    expiry = db.Column(db.DateTime, nullable=True)

    email = db.Column(db.String, nullable=True, index=True)

    product_view_id = db.Column(db.Integer, db.ForeignKey("product_view.id"))

    payment = db.relationship("Payment", backref="voucher")

    # The number of purchases remaining on this voucher
    purchases_remaining = db.Column(db.Integer, nullable=False, server_default="1")

    # The number of adult tickets remaining to purchase on this voucher
    tickets_remaining = db.Column(db.Integer, nullable=False, server_default="2")

    is_used = column_property((purchases_remaining == 0) | (tickets_remaining == 0))

    @classmethod
    def get_by_code(cls, code: str) -> Optional["Voucher"]:
        if not code:
            return None
        return Voucher.query.filter_by(code=code).one_or_none()

    def __init__(
        self,
        view,
        code: Optional[str] = None,
        expiry=None,
        email: Optional[str] = None,
        purchases_remaining: int = 1,
        tickets_remaining: int = 2,
    ):
        super(Voucher, self).__init__()
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
        return (
            self.expiry is not None
            and (self.expiry + VOUCHER_GRACE_PERIOD) < datetime.utcnow()
        )

    def check_capacity(self, basket: Basket):
        """Check if there is enough capacity in this voucher to buy
        the tickets in the provided basket.
        """
        if self.purchases_remaining < 1:
            return False

        adult_tickets = sum(
            line.count for line in basket._lines if line.tier.parent.is_adult_ticket()
        )

        if self.tickets_remaining < adult_tickets:
            return False
        return True

    def consume_capacity(self, payment: Payment):
        """Decrease the voucher's capacity based on tickets in a payment."""
        if self.purchases_remaining < 1:
            raise VoucherUsedError(
                f"Attempting to use voucher with no remaining purchases: {self}"
            )

        adult_tickets = len(
            [
                purchase
                for purchase in payment.purchases
                if purchase.product.is_adult_ticket()
            ]
        )

        if self.tickets_remaining < adult_tickets:
            raise VoucherUsedError(
                f"Attempting to purchase more adult tickets than allowed by voucher: {self}"
            )

        log.info("Consuming 1 purchase and %s tickets from %s", adult_tickets, self)
        self.purchases_remaining = Voucher.purchases_remaining - 1
        self.tickets_remaining = Voucher.tickets_remaining - adult_tickets

    def return_capacity(self, payment: Payment):
        """Return capacity to this voucher based on tickets in a payment."""
        adult_tickets = len(
            [
                purchase
                for purchase in payment.purchases
                if purchase.product.is_adult_ticket()
            ]
        )
        log.info("Returning 1 purchase and %s tickets to %s", adult_tickets, self)
        self.purchases_remaining = Voucher.purchases_remaining + 1
        self.tickets_remaining = Voucher.tickets_remaining + adult_tickets

    def __repr__(self):
        if self.expiry:
            return "<Voucher: %s, view: %s, expiry: %s>" % (
                self.code,
                self.product_view_id,
                self.expiry,
            )
        return "<Voucher: %s, view: %s>" % (self.code, self.product_view_id)

    def is_accessible(self, voucher):
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

    __table_name__ = "product_view"

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String, nullable=False)
    name = db.Column(db.String, nullable=False, index=True)

    # Whether this productview is only accessible to users with an accepted CfP proposal
    cfp_accepted_only = db.Column(db.Boolean, nullable=False, default=False)

    # Whether this productview is only accessible with a voucher associated with this productview
    vouchers_only = db.Column(
        db.Boolean, nullable=False, default=False, server_default="False"
    )

    product_view_products = db.relationship(
        "ProductViewProduct",
        backref="view",
        order_by="ProductViewProduct.order",
        cascade="all, delete-orphan",
    )

    vouchers = db.relationship(
        "Voucher", backref="view", cascade="all, delete-orphan", lazy=True
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
    def get_by_name(cls, name) -> Optional[ProductView]:
        if name is None:
            return None
        return ProductView.query.filter_by(name=name).one_or_none()

    def is_accessible_at(self, user, dt, voucher=None) -> bool:
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

            voucher_obj = Voucher.query.filter_by(view=self, code=voucher).one_or_none()

            if not voucher_obj:
                return False

            return voucher_obj.is_accessible(voucher)

        return True

    def is_accessible(self, user, voucher=None):
        return self.is_accessible_at(user, datetime.utcnow(), voucher=voucher)

    def __repr__(self):
        return "<ProductView: %s>" % self.name

    def __str__(self):
        return self.name


class ProductViewProduct(BaseModel):
    __table_name__ = "product_view_product"
    __export_data__ = False  # Exported by ProductView

    view_id = db.Column(db.Integer, db.ForeignKey(ProductView.id), primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey(Product.id), primary_key=True)

    order = db.Column(db.Integer, nullable=False, default=0)

    def __init__(self, view, product, order=None):
        self.view = view
        self.product = product
        if order is not None:
            self.order = order

    def __repr__(self):
        return "<ProductViewProduct: view {}, product {}, order {}>".format(
            self.view_id, self.product_id, self.order
        )
