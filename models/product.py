from decimal import Decimal

from main import db
from .purchase import Purchase, non_blocking_states, bought_states, allowed_states
from .mixins import CapacityMixin  # , InheritedAttributesMixin


class ProductGroupException(Exception):
    pass


class ProductGroup(db.Model, CapacityMixin):  # , InheritedAttributesMixin):
    """ Represents a logical group of products.

        Capacity and attributes on a ProductGroup cascade down to the products within it.
    """
    __tablename__ = "product_group"

    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("product_group.id"))
    type = db.Column(db.String, nullable=True)

    name = db.Column(db.String, unique=True, nullable=False)
    parent = db.relationship("ProductGroup", remote_side=[id], backref="children", cascade="all")

    def __repr__(self):
        return "<%s: %s>" % (self.__class__.__name__, self.name)

    def get_counts_by_state(self, states_to_get=allowed_states, res=None):
        if res is None:
            res = {}
        if len(res) == 0:
            res = {s: 0 for s in states_to_get}

        for child in self.children:
            res = child.get_counts_by_state(states_to_get, res)
        return res

    def get_sold(self):
        return self.get_counts_by_state(bought_states)

    def get_cheapest(self, currency='gbp', token='', res=None):
        if res is None:
            res = []
        for child in self.children:
            if child.token_correct(token):
                res = child.get_cheapest(currency, token, res)
        res = [r for r in res if r is not None]
        if not res:
            return None
        return min(res, key=lambda x: x['price'])['tier']

    # This is mostly used in testing...
    @classmethod
    def get_by_name(cls, name):
        return ProductGroup.query.filter_by(name=name).first()

    @classmethod
    def get_price_cheapest_full(cls):
        return cls.get_by_name('full').get_cheapest()

    @classmethod
    def get_product_groups_for_token(cls, token):
        return ProductGroup.query.filter_by(discount_token=token, __expired=False).all()


class Product(db.Model, CapacityMixin):  # , InheritedAttributesMixin):
    """ A product (ticket or other item) which is for sale. """
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("product_group.id"), nullable=False)

    name = db.Column(db.String)
    description = db.Column(db.String)
    parent = db.relationship(ProductGroup, backref="products", cascade="all")


class PriceTier(db.Model, CapacityMixin):
    """A pricing level for a Product.

        PriceTiers have a capacity and an expiry through the CapacityMixin.
    """
    id = db.Column(db.Integer, primary_key=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("product.id"), nullable=False)
    parent = db.relationship(Product, backref="price_tiers", cascade="all")

    personal_limit = db.Column(db.Integer, default=10, nullable=False)

    def get_cheapest(self, currency, token='', res=None):
        if res is None:
            res = []
        price = self.get_price(currency)
        res.append({'tier': self, 'price': price.value})
        return res

    def get_price(self, currency):
        price = [p for p in self.prices if p.currency == currency.upper()]
        if len(price) != 1:
            raise ProductGroupException('Unknown currency %s' % currency)
        return price[0]

    def get_counts_by_state(self, states_to_get=allowed_states, res=None):
        if res is None:
            res = {}
        if res == {}:
            res = {s: 0 for s in states_to_get}

        for purchase in self.purchases:
            state = purchase.state
            if state in states_to_get:
                res[state] += 1

        return res

    def user_limit(self, user, token=''):
        if self.has_expired():
            return 0

        if not self.token_correct(token):
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
