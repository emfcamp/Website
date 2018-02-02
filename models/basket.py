from collections import namedtuple
from datetime import datetime, timedelta

from flask import current_app as app

from main import db
from .exc import CapacityException
from .purchase import Purchase, Ticket, AdmissionTicket

Line = namedtuple('Line', 'tier, count, purchases')

class Basket:
    """ Helper class for basket-related operations.
        Created either from Purchases in the DB, or PriceTiers and counts. """
    def __init__(self, user, ids):
        self._loaded = False
        self._lines = None
        self._ids = ids

    @property
    def purchases(self):
        if not self._loaded:
            self.load_purchases()
        return [l.purchases for l in self._lines]

    @property
    def lines(self):
        return [(l.tier, l.count) for l in self._lines]


    def load_purchases(self):
        if self.user.is_anonymous:
            if self.ids:
                purchases = Purchase.query.filter_by(state='reserved', payment_id=None) \
                                          .filter(Purchase.id.in_(self.ids)) \
                                          .order_by(Purchase.id) \
                                          .all()
            else:
                purchases = []

        else:
            # FIXME: is this right?
            purchases = self.user.purchased_products \
                                 .filter_by(state='reserved', payment_id=None) \
                                 .order_by(Purchase.id) \
                                 .all()

        self._purchases = purchases


    def empty(self):
        for line in self.lines:
            for purchase in line.purchases:
                purchase.set_state('cancelled')

            for tier, count in self.lines:
                self.tier.return_instances(count)

        db.session.commit()

    def create_purchases(self, user, currency):
        """ Generate the necessary Purchases for this basket,
            checking capacity from when the objects were loaded. """

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

                price = line.tier.get_price(currency)
                line.purchases += [purchase_cls(price=price, user=user) for _ in range(issue_count)]

            # If there are already reserved tickets, leave them.
            # The user will complete their purchase soon.


    def ensure_purchase_capacity(self):
        """ Actually check the capacity.  """
        db.session.flush()
        for tier, count in self.lines:
            if tier.get_total_remaining_capacity() < 0:
                # explicit rollback - we don't want this exception ignored
                db.session.rollback()
                raise CapacityException('Insufficient capacity.')

    def cancel_extra_purchases(self):
        # FIXME: track extra purchases separately after initialisation?
        for line in self._lines:
            return_count = len(line.purchases) - line.count
            if return_count > 0:
                for _, purchase in zip(range(return_count, line.purchases)):
                    purchase.set_state('cancelled')

                line.tier.return_instances(return_count)


    def create_payment(self, payment_cls, currency):
        """
        Insert payment and purchases from session data into DB
        """

        if not self.purchases:
            return None

        for purchase in self.purchases:
            if purchase.price.currency != currency:
                raise Exception("Currency mismatch got: {}, expected: {}".format(currency, purchase.price.currency))

            purchase.user = self.user

        payment = payment_cls(currency, self.total)
        # This is where you'd add the premium if it existed

        self.user.payments.append(payment)

        app.logger.info('Creating purchases for basket %s', self)
        app.logger.info('Payment: %s for %s %s (purchase total %s)', payment_cls.name,
                        payment.amount, currency, self.total)

        # FIXME: move this to banktransfer_start?
        if currency == 'GBP':
            days = app.config.get('EXPIRY_DAYS_TRANSFER')
        elif currency == 'EUR':
            days = app.config.get('EXPIRY_DAYS_TRANSFER_EURO')

        payment.expires = datetime.utcnow() + timedelta(days=days)

        # FIXME: I've conflated all purchases from "required" purchases
        for purchase in self.purchases:
            purchase.payment = payment
            purchase.set_user(self.user)

        return payment


