from decimal import Decimal
from sqlalchemy import func

from main import db
from .purchase import Purchase, non_blocking_states, allowed_states
from .mixins import CapacityMixin, InheritedAttributesMixin


class ProductGroupException(Exception):
    pass


class ProductGroup(db.Model, CapacityMixin, InheritedAttributesMixin):
    """ Represents a logical group of products.

        Capacity and attributes on a ProductGroup cascade down to the products within it.
    """
    __tablename__ = "product_group"

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("product_group.id"))
    type = db.Column(db.String, nullable=True)

    name = db.Column(db.String, unique=True, nullable=False)
    parent = db.relationship("ProductGroup", remote_side=[id], backref="children", cascade="all")

    @classmethod
    def get_by_name(cls, name):
        return ProductGroup.query.filter_by(name=name).first()

    def get_purchase_count_by_state(self, states_to_get=None):
        """ Return a count of purchases, broken down by state.
            Optionally filter the states required to `states_to_get`.

            Returns a dictionary of state -> count"""
        if states_to_get is None:
            states_to_get = allowed_states
        res = {state: 0 for state in states_to_get}

        for child in self.children:
            for k, v in child.get_purchase_count_by_state(states_to_get).items():
                res[k] += v

        for product in self.products:
            for k, v in product.get_purchase_count_by_state(states_to_get).items():
                res[k] += v
        return res

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self.name)


class Product(db.Model, CapacityMixin, InheritedAttributesMixin):
    """ A product (ticket or other item) which is for sale. """
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("product_group.id"), nullable=False)

    # TODO: Do we need both name and display_name? Is it just because of the creation task?
    # Can we fix that with an admin interface and fixtures?
    # (We also need to identify the "full ticket" product to display the price on the
    # front page)
    name = db.Column(db.String, nullable=False)
    display_name = db.Column(db.String)
    description = db.Column(db.String)
    parent = db.relationship(ProductGroup, backref="products", cascade="all")

    @classmethod
    def get_by_name(cls, name):
        return Product.query.filter_by(name=name).first()

    @classmethod
    def get_cheapest_price(cls, product_name='full'):
        return cls.get_by_name(product_name).get_price('GBP')

    def get_purchase_count_by_state(self, states_to_get=None):
        """ Return a count of purchases, broken down by state.
            Optionally filter the states required to `states_to_get`.

            Returns a dictionary of state -> count"""
        if states_to_get is None:
            states_to_get = allowed_states

        # Don't cascade down here for performance reasons, do a direct query.
        cls = Purchase.class_from_product(self)
        res = db.session.query(cls.state, func.count(cls.id)).\
            join(PriceTier).\
            filter(PriceTier.id.in_(t.id for t in self.price_tiers)).\
            filter(cls.state.in_(states_to_get)).\
            group_by(cls.state).all()
        states = {state: 0 for state in states_to_get}
        for k, v in res:
            states[k] += v
        return states

    def get_price(self, currency):
        """ Fetch the cheapest price for this product in a given currency.

            Returns a Price object, or None if no price was found.
        """
        return self.__get_cheapest_tier_price_pair(currency)[1]

    def get_lowest_price_tier(self, currency='GBP'):
        """ Fetch the cheapest price tier for this product.

            An optional argument, currency, can be specified with which to check
            the price. Defaults to GBP.

            Returns a PriceTier object, or None if no price found.
        """
        return self.__get_cheapest_tier_price_pair(currency)[0]

    def __get_cheapest_tier_price_pair(self, currency):
        pairs = [(tier, tier.get_price(currency)) for tier in self.price_tiers]
        pairs = list(sorted(pairs, key=lambda p: p[1].price_int))
        if len(pairs) == 0:
            return None
        return pairs[0]

    def get_type(self):
        """ Return the type of this product (ticket, merchandise, etc).

            We'll iterate up the product tree until we find the type.
        """
        obj = self.parent
        while getattr(obj, 'type') is None or obj.type is None:
            if obj.parent is None:
                return None
            obj = obj.parent
        return obj.type

    def __repr__(self):
        return "<Product: %s>" % self.name


class PriceTier(db.Model, CapacityMixin):
    """A pricing level for a Product.

        PriceTiers have a capacity and an expiry through the CapacityMixin.
        They have one Price object per currency.
    """
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    parent = db.relationship(Product, backref="price_tiers", cascade="all")

    personal_limit = db.Column(db.Integer, default=10, nullable=False)

    @classmethod
    def get_by_name(cls, name):
        # FIXME: Do we need to get this by name - does it *need* a name?
        # I think this might only be because of tests and creation.
        return PriceTier.query.filter_by(name=name).first()

    def get_purchase_count_by_state(self, states_to_get=None):
        """ Return a count of purchases, broken down by state.
            Optionally filter the states required to `states_to_get`.

            Returns a dictionary of state -> count"""
        if states_to_get is None:
            states_to_get = allowed_states

        cls = Purchase.class_from_product(self.parent)
        res = db.session.query(cls.state, func.count(cls.id)).\
            filter(cls.price_tier == self).\
            filter(cls.state.in_(states_to_get)).\
            group_by(cls.state).all()

        states = {state: 0 for state in states_to_get}
        for k, v in res:
            states[k] += v
        return states

    def get_price(self, currency):
        """ Get the price for this tier in the given currency.

            Returns a Price object, or None if no price was found.
        """
        for price in self.prices:
            if price.currency == currency.upper():
                return price
        return None

    def user_limit(self, user, token=''):
        if self.has_expired():
            return 0

        if user.is_authenticated:
            # How many have been sold to this user
            user_count = Purchase.query.filter(
                Purchase.price_tier == self,
                Purchase.purchaser == user,
                ~Purchase.state.in_(non_blocking_states)
            ).count()
        else:
            user_count = 0

        return min(self.personal_limit - user_count, self.get_total_remaining_capacity())

    def __repr__(self):
        return "<PriceTier %s>" % self.name


class Price(db.Model):
    """ Represents the price of a product, at a given price tier, in a given currency.

        Prices are immutable and should not be changed!
    """
    __tablename__ = "product_price"

    id = db.Column(db.Integer, primary_key=True)
    price_tier_id = db.Column(db.Integer, db.ForeignKey("price_tier.id"), nullable=False)
    currency = db.Column(db.String, nullable=False)
    price_int = db.Column(db.Integer, nullable=False)
    price_tier = db.relationship(PriceTier, backref=db.backref("prices", cascade="all"))

    def __init__(self, currency=None, **kwargs):
        super().__init__(currency=currency.upper(), **kwargs)

    @property
    def value(self):
        return Decimal(self.price_int) / 100

    @value.setter
    def value(self, val):
        self.price_int = int(val * 100)

    def __repr__(self):
        return "<Price for %r: %.2f %s>" % (self.price_tier, self.value, self.currency)
