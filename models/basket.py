from collections.abc import MutableMapping
from itertools import groupby

from flask import current_app as app, session
from sqlalchemy.orm import joinedload

from main import db
from .exc import CapacityException
from .product import Voucher
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

    def __init__(self, user, currency, voucher=None):
        self.user = user
        # Due to the Price, reserved Purchases have an implicit currency,
        # but this shouldn't be relied on until they're attached to a Payment.
        # Totals should be calculated based on the basket's currency.
        self.currency = currency
        self._lines = []
        self.voucher = voucher

    @classmethod
    def from_session(self, user, currency):
        purchases = session.get("basket_purchase_ids", [])
        surplus_purchases = session.get("basket_surplus_purchase_ids", [])
        voucher = session.get("ticket_voucher", None)

        basket = Basket(user, currency, voucher)
        basket.load_purchases_from_ids(purchases, surplus_purchases)
        return basket

    @classmethod
    def clear_from_session(self):
        session.pop("basket_purchase_ids", None)
        session.pop("basket_surplus_purchase_ids", None)

    def save_to_session(self):
        session["basket_purchase_ids"] = [p.id for p in self.purchases]
        session["basket_surplus_purchase_ids"] = [p.id for p in self.surplus_purchases]

    def _get_line(self, tier):
        for line in self._lines:
            if line.tier == tier:
                return line

        raise KeyError("Tier {} not found in basket".format(tier))

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
        lines = ["{} {}".format(line.count, line.tier) for line in self._lines]
        return "<Basket {} ({} {})>".format(",".join(lines), self.total, self.currency)

    @property
    def purchases(self):
        return [p for line in self._lines for p in line.purchases[: line.count]]

    @property
    def surplus_purchases(self):
        return [p for line in self._lines for p in line.purchases[line.count :]]

    def set_currency(self, currency):
        # We do this half to save loading the wrong prices on the next page,
        # and half so there's a record of how often currency changes happen.
        # When Basket is stored in the DB, we'll just update it there.
        for line in self._lines:
            for purchase in line.purchases:
                purchase.change_currency(currency)

    @property
    def total(self):
        total = 0
        for line in self._lines:
            price = line.tier.get_price(self.currency)
            total += price.value * line.count

        return total

    def load_purchases(self, purchases, chosen_ids=None):
        def get_pt(p):
            return p.price_tier

        purchases = sorted(purchases, key=get_pt)
        for tier, tier_purchases in groupby(purchases, get_pt):
            tier_purchases = sorted(tier_purchases, key=lambda p: p.id)

            if chosen_ids is not None:
                purchases = [p for p in tier_purchases if p.id in chosen_ids]
                surplus_purchases = [
                    p for p in tier_purchases if p.id not in chosen_ids
                ]
            else:
                purchases = tier_purchases
                surplus_purchases = []

            app.logger.debug(
                "Basket line: %s %s %s", tier, purchases, surplus_purchases
            )
            self._lines.append(
                Line(tier, len(purchases), purchases + surplus_purchases)
            )

    def load_purchases_from_ids(self, chosen_ids, surplus_ids):
        chosen_ids = set(chosen_ids)
        surplus_ids = set(surplus_ids)
        if chosen_ids | surplus_ids:
            purchases = (
                Purchase.query.filter_by(state="reserved", payment_id=None)
                .filter(Purchase.id.in_(chosen_ids | surplus_ids))
                .options(joinedload(Purchase.price_tier))
            )

            self.load_purchases(purchases, chosen_ids)

    def load_purchases_from_db(self):
        purchases = (
            Purchase.query.filter_by(state="reserved", payment_id=None)
            .filter(Purchase.owner_id == self.user.id)
            .options(joinedload(Purchase.price_tier))
        )
        self.load_purchases(purchases)

    def create_purchases(self):
        """ Generate the necessary Purchases for this basket,
            checking capacity from when the objects were loaded. """

        user = self.user
        if user.is_anonymous:
            user = None

        purchases_to_flush = []
        with db.session.no_autoflush:
            for line in self._lines:
                issue_count = line.count - len(line.purchases)
                if issue_count > 0:

                    # user_limit takes into account existing purchases
                    if issue_count > line.tier.user_limit():
                        raise CapacityException(
                            "Insufficient capacity for tier %s." % line.tier
                        )

                    line.tier.issue_instances(issue_count)

                    product = line.tier.parent
                    if product.parent.type == "admissions":
                        purchase_cls = AdmissionTicket
                    elif product.parent.type in {"campervan", "parking"}:
                        purchase_cls = Ticket
                    else:
                        purchase_cls = Purchase

                    price = line.tier.get_price(self.currency)
                    purchases = [
                        purchase_cls(price=price, user=user) for _ in range(issue_count)
                    ]
                    line.purchases += purchases
                    purchases_to_flush += purchases

                # If there are already reserved tickets, leave them.
                # The user will complete their purchase soon.

        # Insert the purchases right away, as column_property and
        # polymorphic columns are reloaded from the DB after insert
        db.session.flush(purchases_to_flush)

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
                raise CapacityException("Insufficient capacity.")

    def cancel_purchases(self):
        with db.session.no_autoflush:
            for line in self._lines:
                for purchase in line.purchases:
                    purchase.cancel()

        self._lines = []

    def cancel_surplus_purchases(self):
        """
        Return unnecessary reservations. This will typically be done after
        creating the payment object, so users don't find they've lost a ticket
        after originally reserving it.
        """
        with db.session.no_autoflush:
            for line in self._lines:
                if line.count < len(line.purchases):
                    for purchase in line.purchases[line.count :]:
                        purchase.cancel()

                    line.purchases = line.purchases[: line.count]

    def check_out_free(self):
        if self.total != 0:
            raise Exception(
                "Cannot check out free basket with total of {}".format(self.total)
            )

        if self.user is None:
            raise Exception("Cannot check out basket with no user")

        for purchase in self.purchases:
            if purchase.owner is None:
                purchase.set_user(self.user)
            purchase.set_state("paid")

    def create_payment(self, payment_cls):
        """
        Insert payment and purchases from session data into DB.

        This must be done after creating the purchases.
        """

        if not self.purchases:
            return None

        for purchase in self.purchases:
            # Reserved purchases can be of a different currency if they were
            # recovered into separate sessions, or specified in the reserved URL
            purchase.change_currency(self.currency)

            if purchase.state != "reserved":
                raise Exception(
                    "Purchase {} state is {}, not reserved".format(
                        purchase.id, purchase.state
                    )
                )

            if purchase.payment_id is not None:
                raise Exception("Purchase {} has a payment already".format(purchase.id))

        payment = payment_cls(self.currency, self.total, self.voucher)
        del session["ticket_voucher"]

        # This is where you'd add the premium if it existed

        self.user.payments.append(payment)

        app.logger.info("Creating payment for basket %s", self)
        app.logger.info(
            "Payment: %s for %s %s (purchase total %s)",
            payment_cls.name,
            payment.amount,
            self.currency,
            self.total,
        )

        for purchase in self.purchases:
            purchase.payment = payment
            if purchase.purchaser_id is None:
                purchase.set_user(self.user)

        if self.voucher:
            # Reduce the capacity of the voucher based on this payment.
            voucher_obj = Voucher.get_by_code(self.voucher)
            voucher_obj.consume_capacity(payment)
            db.session.add(voucher_obj)

        return payment

    @property
    def requires_shipping(self):
        for line in self._lines:
            product = line.tier.parent
            if product.attributes.get("requires_shipping"):
                return True

        return False
