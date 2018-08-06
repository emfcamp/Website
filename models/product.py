from decimal import Decimal
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import validates
from sqlalchemy import func, UniqueConstraint, inspect
from sqlalchemy.ext.associationproxy import association_proxy

from main import db
from .mixins import CapacityMixin, InheritedAttributesMixin
from . import config_date
from .purchase import Purchase


class ProductGroupException(Exception):
    pass

class MultipleLoadedResultsFound(Exception):
    pass

def one_or_none(result):
    if len(result) == 1:
        return result[0]
    if len(result) == 0:
        return None
    raise MultipleLoadedResultsFound()

class ProductGroup(db.Model, CapacityMixin, InheritedAttributesMixin):
    """ Represents a logical group of products.

        Capacity and attributes on a ProductGroup cascade down to the products within it.
    """
    __tablename__ = "product_group"

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("product_group.id"))
    type = db.Column(db.String, nullable=False)
    name = db.Column(db.String, unique=True, nullable=False)

    products = db.relationship('Product', backref='parent', cascade='all',
                               order_by='Product.id')
    children = db.relationship('ProductGroup', backref=db.backref('parent', remote_side=[id]),
                               cascade='all', order_by='ProductGroup.id')

    def __init__(self, type=None, parent=None, parent_id=None, **kwargs):
        # XXX: Why are we specifying both parent and parent_id here?
        # Should also have mandatory argument for name.
        if type is None:
            if parent is None:
                type = ProductGroup.query.get(parent_id).type
            else:
                type = parent.type

        if type is None:
            raise ValueError('ProductGroup requires a type')

        super().__init__(type=type, parent=parent, parent_id=parent_id, **kwargs)

    @classmethod
    def get_by_name(cls, group_name):
        return ProductGroup.query.filter_by(name=group_name).one_or_none()

    @validates('capacity_max')
    def validate_capacity_max(self, _, capacity_max):
        """ Validate the following rules for ProductGroup capacity on allocation-level
            ProductGroups:

            - If a parent ProductGroup has a max capacity set, either all child ProductGroups
                must have it set, or they must all be None.

            - The sum of child ProductGroup capacities cannot exceed the parent
                ProductGroup capacity.
        """

        if self.capacity_used is not None and capacity_max is not None and capacity_max < self.capacity_used:
            raise ValueError("capacity_max cannot be lower than capacity_used")

        if not self.parent or self.parent.capacity_max is None:
            return capacity_max

        with db.session.no_autoflush:
            # Disable autoflush in case we're in an initialiser
            siblings = list(self.parent.children)

        if self in siblings:
            siblings.remove(self)

        if capacity_max is None:
            if any(sibling.capacity_max for sibling in siblings):
                raise ValueError("capacity_max must be provided if siblings have capacity_max set.")
        else:
            if any(sibling.capacity_max is None for sibling in siblings):
                raise ValueError("One or more sibling ProductGroups has a None capacity. "
                                 "This is a bug and you should fix that first.")

            sibling_capacity = sum(sibling.capacity_max for sibling in siblings)
            if sibling_capacity + capacity_max > self.parent.capacity_max:
                raise ValueError("New capacity_max (%s) + sum of sibling capacities (%s) exceeds "
                                 "parent ProductGroup capacity (%s)." % (capacity_max, sibling_capacity,
                                                                         self.parent.capacity_max))
        return capacity_max


    @property
    def unallocated_capacity(self):
        """ If this is an allocation-level ProductGroup (i.e. it has a capacity_max
            set, and all childen also do), return the total unallocated capacity.

            Otherwise, return None.
        """

        if self.capacity_max is None or len(self.children) == 0 or \
                any(child.capacity_max is None for child in self.children):
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

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self.name)

    def __str__(self):
        return self.name

class Product(db.Model, CapacityMixin, InheritedAttributesMixin):
    """ A product (ticket or other item) which is for sale. """
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey(ProductGroup.id), nullable=False)
    name = db.Column(db.String, nullable=False)
    display_name = db.Column(db.String)
    description = db.Column(db.String)
    price_tiers = db.relationship('PriceTier', backref='parent', cascade='all', order_by='PriceTier.id')
    product_view_products = db.relationship('ProductViewProduct', backref='product', cascade='all, delete-orphan')

    __table_args__ = (
        UniqueConstraint('name', 'group_id'),
    )

    @classmethod
    def get_by_name(cls, group_name, product_name):
        group = ProductGroup.query.filter_by(name=group_name)
        product = group.join(Product).filter_by(name=product_name).with_entities(Product)
        return product.one_or_none()

    @property
    def purchase_count_by_state(self):
        states = Purchase.query.join(PriceTier, Product) \
                               .filter(Product.id == self.id) \
                               .with_entities(Purchase.state, func.count(Purchase.id)) \
                               .group_by(Purchase.state)

        return dict(states)

    def get_cheapest_price(self, currency='GBP'):
        price = PriceTier.query.filter_by(product_id=self.id) \
                         .join(Price).filter_by(currency=currency) \
                         .with_entities(Price) \
                         .order_by(Price.price_int).first()
        return price

    def get_price_tier(self, name):
        tier = PriceTier.query.filter_by(product_id=self.id) \
                        .filter_by(name=name)
        return tier.one_or_none()

    def __repr__(self):
        return "<Product: %s>" % self.name

    def __str__(self):
        return self.name

class PriceTier(db.Model, CapacityMixin):
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

    __table_args__ = (
        UniqueConstraint('name', 'product_id'),
    )
    prices = db.relationship('Price', backref='price_tier', cascade='all', order_by='Price.id')

    def __init__(self, name=None, **kwargs):
        super().__init__(name=name, **kwargs)

    @classmethod
    def get_by_name(cls, group_name, product_name, tier_name):
        group = ProductGroup.query.filter_by(name=group_name)
        product = group.join(Product).filter_by(name=product_name).with_entities(Product)
        tier = product.join(PriceTier).filter_by(name=tier_name).with_entities(PriceTier)
        return tier.one_or_none()

    @property
    def purchase_count_by_state(self):
        states = Purchase.query.join(PriceTier) \
                               .filter(PriceTier.id == self.id) \
                               .with_entities(Purchase.state, func.count(Purchase.id)) \
                               .group_by(Purchase.state)

        return dict(states)

    @property
    def purchase_count(self):
        return Purchase.query.join(PriceTier).filter(PriceTier.id == self.id).count()

    @property
    def unused(self):
        """ Whether this tier is unused and can be safely deleted. """
        return self.purchase_count == 0 and not self.active

    def get_price(self, currency):
        if 'prices' in inspect(self).unloaded:
            return self.get_price_unloaded(currency)
        else:
            return self.get_price_loaded(currency)

    def get_price_unloaded(self, currency):
        price = Price.query.filter_by(price_tier_id=self.id, currency=currency)
        return price.one_or_none()

    def get_price_loaded(self, currency):
        prices = [p for p in self.prices if p.currency == currency]
        return one_or_none(prices)

    def user_limit(self):
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


class Price(db.Model):
    """ Represents the price of a product, at a given price tier, in a given currency.

        Prices are immutable and should not be changed. We expire the PriceTier instead.
    """
    __tablename__ = "price"

    id = db.Column(db.Integer, primary_key=True)
    price_tier_id = db.Column(db.Integer, db.ForeignKey("price_tier.id"), nullable=False)
    currency = db.Column(db.String, nullable=False)
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
        return self.value / Decimal('1.2')

    @value_ex_vat.setter
    def value_ex_vat(self, val):
        self.value = val * Decimal('1.2')

    def __repr__(self):
        return "<Price for %r: %.2f %s>" % (self.price_tier, self.value, self.currency)

    def __str__(self):
        return '%0.2f %s' % (self.value, self.currency)


class ProductView(db.Model):
    __table_name__ = 'product_view'

    """ A selection of products to be shown together for sale. """
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String, nullable=False)
    name = db.Column(db.String, nullable=False, index=True)
    token = db.Column(db.String, nullable=True)
    cfp_accepted_only = db.Column(db.Boolean, nullable=False, default=False)

    product_view_products = db.relationship('ProductViewProduct', backref='view',
                                            order_by='ProductViewProduct.order', cascade='all, delete-orphan')
    products = association_proxy('product_view_products', 'product')

    @classmethod
    def get_by_name(cls, name):
        if name is None:
            return None
        return ProductView.query.filter_by(name=name).one_or_none()

    @classmethod
    def get_by_token(cls, token):
        if token is None:
            return None
        return ProductView.query.filter_by(token=token).one_or_none()

    def is_accessible(self, user, user_token=None):
        " Whether this ProductView is accessible to a user."
        if user.is_authenticated and user.has_permission('admin'):
            # Admins always have access
            return True

        if not self.token and datetime.utcnow() < config_date('SALES_START'):
            # If TICKET_SALES is set, but sales haven't started, restrict access to token views
            return False

        if self.token and user_token != self.token:
            # Invalid token
            return False

        if self.cfp_accepted_only and (not user.is_authenticated or not user.is_cfp_accepted):
            # cfp_accepted and token is an either-or thing currently
            return False

        return True

    def __repr__(self):
        return "<ProductView: %s>" % self.name

    def __str__(self):
        return self.name

class ProductViewProduct(db.Model):
    __table_name__ = 'product_view_product'

    view_id = db.Column(db.Integer, db.ForeignKey(ProductView.id), primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey(Product.id), primary_key=True)

    order = db.Column(db.Integer, nullable=False, default=0)

    def __init__(self, view, product, order=None):
        self.view = view
        self.product = product
        if order is not None:
            self.order = order

    def __repr__(self):
        return '<ProductViewProduct: view {}, product {}, order {}>'.format(
            self.view_id, self.product_id, self.order)


