from decimal import Decimal
from collections import defaultdict

from sqlalchemy import func, UniqueConstraint, inspect
from sqlalchemy.ext.associationproxy import association_proxy

from main import db
from .purchase import Purchase
from .mixins import CapacityMixin, InheritedAttributesMixin


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
        if type is None:
            if parent is None:
                type = ProductGroup.query.get(parent_id).type
            else:
                type = parent.type

        super().__init__(type=type, parent=parent, parent_id=parent_id, **kwargs)

    @classmethod
    def get_by_name(cls, group_name):
        return ProductGroup.query.filter_by(name=group_name).one_or_none()

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
    product_view_products = db.relationship('ProductViewProduct', backref='product')

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

    def __init__(self, currency, **kwargs):
        super().__init__(currency=currency.upper(), **kwargs)

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
    name = db.Column(db.String, nullable=False, index=True)
    token = db.Column(db.String, nullable=True)

    product_view_products = db.relationship('ProductViewProduct', backref='view', order_by='ProductViewProduct.order')
    products = association_proxy('product_view_products', 'product')

    def __init__(self, name):
        self.name = name

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

