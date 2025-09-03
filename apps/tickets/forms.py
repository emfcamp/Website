from flask import current_app as app
from flask import render_template_string, url_for
from flask_login import current_user
from markupsafe import Markup
from wtforms import (
    BooleanField,
    FieldList,
    FormField,
    HiddenField,
    StringField,
    SubmitField,
)
from wtforms.validators import DataRequired, InputRequired, Optional, ValidationError

from models import Currency
from models.basket import Basket
from models.payment import BankPayment, StripePayment
from models.product import PriceTier, Product, Voucher
from models.user import User

from ..common.fields import EmailField, HiddenIntegerField, IntegerSelectField
from ..common.forms import Form


class TicketAmountForm(Form):
    amount = IntegerSelectField("Number of tickets", [Optional()])
    tier_id = HiddenIntegerField("Price tier", [InputRequired()])


class TicketAmountsForm(Form):
    """The main ticket selection form"""

    tiers = FieldList(FormField(TicketAmountForm))
    buy_tickets = SubmitField("Buy Tickets")
    buy_hire = SubmitField("Order")
    buy_other = SubmitField("Buy")
    currency_code = HiddenField("Currency")
    set_currency = StringField("Set Currency", [Optional()])

    def __init__(self, products: list[Product]):
        self._tiers = self._get_price_tiers(products)
        super().__init__()

    def _get_price_tiers(_self, products: list[Product]) -> dict[int, PriceTier]:
        """Get the price tiers we want to show in this form"""
        # Order of tiers is important, but dict is ordered these days
        tiers = {}
        for product in products:
            pts = [tier for tier in product.price_tiers if tier.active]
            if len(pts) > 1:
                app.logger.error(
                    "Multiple active PriceTiers found for %s. Excluding product.",
                    product,
                )
                continue

            pt = pts[0]
            tiers[pt.id] = pt
        return tiers

    def populate(form, basket):
        """Populate the form with price tiers, with the amount pre-filled from
        the user's basket.

        This is only called when the form is initially generated, not when it's
        submitted (as the tiers in the form already exist then).
        """
        for pt_id, tier in form._tiers.items():
            form.tiers.append_entry()
            f = form.tiers[-1]
            f.tier_id.data = pt_id

            f.amount.data = basket.get(tier, 0)

    def ensure_capacity(form, basket: Basket, voucher: Voucher | None):
        """
        This function updates the products on the form based on the current capacity
        so it will fail to validate if the requested ticket capacity is now unavailable.
        """

        # FIXME: We're storing data in random attributes of the FormField object here,
        # which the typechecker doesn't really like.

        # Whether submitted or not, update the allowed amounts before validating
        capacity_available = True
        for f in form.tiers:
            pt_id = f.tier_id.data
            tier = form._tiers[pt_id]
            f._tier = tier  # type: ignore[attr-defined]

            # If they've already got reserved tickets, they can keep them
            # because they've been reserved in the database
            user_limit = max(tier.user_limit(), basket.get(tier, 0))

            # If a voucher is being used, limit the number of adult tickets by however
            # many remain on the voucher
            if voucher and tier.parent.is_adult_ticket():
                user_limit = min(user_limit, voucher.tickets_remaining)

            if f.amount.data and f.amount.data > user_limit:
                f.amount.data = user_limit
                capacity_available = False

            values = range(user_limit + 1)
            f.form.amount.values = values
            f._any = any(values)  # type: ignore[attr-defined]
        return capacity_available

    def add_to_basket(form, basket):
        """Add selected tickets to the provided basket."""
        for f in form.tiers:
            pt = f._tier
            if f.amount.data != basket.get(pt, 0):
                app.logger.info("Adding %s %s tickets to basket", f.amount.data, pt.name)
                basket[pt] = f.amount.data

    def validate_set_currency(form, field):
        try:
            Currency(field.data)
        except ValueError as e:
            raise ValidationError(f"Invalid currency {field.data}") from e


class TicketTransferForm(Form):
    name = StringField("Name", [DataRequired()])
    email = EmailField("Email")

    transfer = SubmitField("Transfer Ticket")

    def validate_email(form, field):
        if current_user.email == field.data:
            raise ValidationError("You cannot transfer a ticket to yourself")


class TicketPaymentForm(Form):
    email = EmailField("Email")
    name = StringField("Name", [DataRequired()])
    allow_promo = BooleanField("Send me occasional emails about future EMF events")
    basket_total = HiddenField("basket total")

    banktransfer = SubmitField("Pay by Bank Transfer")
    stripe = SubmitField("Pay by card")

    def validate_email(form, field):
        if current_user.is_anonymous and User.does_user_exist(field.data):
            field.was_duplicate = True
            pay_url = url_for("tickets.pay", flow=form.flow)

            msg = Markup(
                render_template_string(
                    'Account already exists. Please <a href="{{ url }}">click here</a> to log in.',
                    url=url_for("users.login", next=pay_url, email=field.data),
                )
            )
            raise ValidationError(msg)

    def get_payment_class(form):
        if form.banktransfer.data:
            return BankPayment
        if form.stripe.data:
            return StripePayment
        raise ValueError("Cannot identify payment form type")


class TicketPaymentShippingForm(TicketPaymentForm):
    address_1 = StringField("Address", [DataRequired()])
    address_2 = StringField("Address", [])
    town = StringField("Town", [DataRequired()])
    postcode = StringField("Postal code", [DataRequired()])
    country = StringField("Country", [DataRequired()])
