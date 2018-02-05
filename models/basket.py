from collections.abc import MutableMapping
from itertools import groupby

from flask import current_app as app
from sqlalchemy.orm import joinedload

from main import db
from .exc import CapacityException
from .purchase import Purchase, Ticket, AdmissionTicket

class Line:
    def __init__(self, tier, count, purchases=None):
        self.tier = tier
        self.count = count
        if purchases is None:
            purchases = []
        self.purchases = purchases


class Basket(MutableMapping):
    """
    Helper class for basket-related operations. Tied to a user, and maps PriceTiers to counts.

    Created either from Purchases in the DB, or a list of PriceTiers and counts.
    ids should be trustworthy (e.g. stored in flask.session)
    """

    def __init__(self, user, currency, ids):
        self.user = user
        self.currency = currency
        self._lines = []
        self._ids = ids
        self.load_purchases()

    def _get_line(self, tier):
        for line in self._lines:
            if line.tier == tier:
                return line

        raise KeyError('Tier {} not found in basket'.format(tier))

    def __getitem__(self, key):
        return self._get_line(key).count

    def __setitem__(self, key, value):
        try:
            line = self._get_line(key)
            line.count = value

        except KeyError:
            self._lines.append(Line(key, value))

    def __delitem__(self, key):
        line = self._get_line(key)
        self._lines.remove(line)

    def __iter__(self):
        for line in list(self._lines):
            yield line.tier

    def __len__(self):
        return len(self._lines)

    def __str__(self):
        lines = ['{} {}'.format(line.count, line.tier) for line in self._lines]
        return '<Basket {} ({} {})>'.format(','.join(lines), self.total, self.currency)


    @property
    def purchases(self):
        return [p for line in self._lines for p in line.purchases]

    @property
    def total(self):
        total = 0
        for line in self._lines:
            price = line.tier.get_price(self.currency)
            total += price.value * line.count

        return total

    def load_purchases(self):
        if self._ids:
            purchases = set(
                Purchase.query.filter_by(state='reserved', payment_id=None)
                              .filter(Purchase.id.in_(self._ids))
                              .options(joinedload(Purchase.price_tier))
            )

        else:
            purchases = set()

        if self.user.is_authenticated:
            purchases |= set(
                self.user.purchased_products
                         .filter_by(state='reserved', payment_id=None)
                         .options(joinedload(Purchase.price_tier))
            )

        def get_pt(p):
            return p.price_tier

        purchases = sorted(purchases, key=get_pt)
        for tier, tier_purchases in groupby(purchases, get_pt):
            tier_purchases = list(tier_purchases)
            self._lines.append(Line(tier, len(tier_purchases), tier_purchases))


    def create_purchases(self):
        """ Generate the necessary Purchases for this basket,
            checking capacity from when the objects were loaded. """

        user = self.user
        if user.is_anonymous:
            user = None

        with db.session.no_autoflush:
            for line in self._lines:
                issue_count = line.count - len(line.purchases)
                if issue_count > 0:

                    # user_limit takes into account existing purchases
                    if issue_count > line.tier.user_limit():
                        raise CapacityException('Insufficient capacity.')

                    line.tier.issue_instances(issue_count)

                    product = line.tier.parent
                    if product.parent.type == 'admissions':
                        purchase_cls = AdmissionTicket
                    elif product.parent.type in {'campervan', 'parking'}:
                        purchase_cls = Ticket
                    else:
                        purchase_cls = Purchase

                    price = line.tier.get_price(self.currency)
                    line.purchases += [purchase_cls(price=price, user=user) for _ in range(issue_count)]

                # If there are already reserved tickets, leave them.
                # The user will complete their purchase soon.

    def ensure_purchase_capacity(self):
        """
        Get the DB to lock and update the rows, and then check capacity.

        This could be moved to an after_flush handler for CapacityMixin.
        """
        db.session.flush()
        for line in self._lines:
            if line.tier.get_total_remaining_capacity() < 0:
                # explicit rollback - we don't want this exception ignored
                db.session.rollback()
                raise CapacityException('Insufficient capacity.')

    def cancel_purchases(self):
        with db.session.no_autoflush:
            for line in self._lines:
                for purchase in line.purchases:
                    purchase.set_state('cancelled')

                line.tier.return_instances(len(line.purchases))
                line.purchases = []

    def cancel_extra_purchases(self):
        """
        Return unnecessary reservations. This will typically be done after
        creating the payment object, so users don't find they've lost a ticket
        after originally reserving it.
        """
        with db.session.no_autoflush:
            for line in self._lines:
                return_count = len(line.purchases) - line.count
                if return_count > 0:
                    # cancel purchases from the end
                    for _, purchase in zip(range(return_count), reversed(line.purchases)):
                        purchase.set_state('cancelled')

                    line.tier.return_instances(return_count)
                    line.purchases = line.purchases[:line.count]


    def create_payment(self, payment_cls):
        """
        Insert payment and purchases from session data into DB.

        This must be done after creating the purchases.
        """

        if not self.purchases:
            return None

        for purchase in self.purchases:
            # Sanity checks for possible race conditions
            if purchase.price.currency != self.currency:
                raise Exception("Currency mismatch got: {}, expected: {}".format(self.currency, purchase.price.currency))

            if purchase.state != 'reserved':
                raise Exception("Purchase {} state is {}, not reserved".format(purchase.id, purchase.state))

            if purchase.payment_id is not None:
                raise Exception("Purchase {} has a payment already".format(purchase.id))

            purchase.user = self.user

        payment = payment_cls(self.currency, self.total)

        # This is where you'd add the premium if it existed

        self.user.payments.append(payment)

        app.logger.info('Creating payment for basket %s', self)
        app.logger.info('Payment: %s for %s %s (purchase total %s)', payment_cls.name,
                        payment.amount, self.currency, self.total)

        for purchase in self.purchases:
            purchase.payment = payment
            if purchase.purchaser_id is None:
                purchase.set_user(self.user)

        return payment


