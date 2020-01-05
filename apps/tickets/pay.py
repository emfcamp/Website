from decimal import Decimal

from flask import (
    render_template,
    redirect,
    request,
    flash,
    url_for,
    session,
    abort,
    current_app as app,
)
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from main import db
from models.user import UserShipping
from models.basket import Basket
from models.payment import BankPayment, StripePayment, GoCardlessPayment

from ..common import get_user_currency, set_user_currency, create_current_user
from ..payments.gocardless import gocardless_start
from ..payments.banktransfer import transfer_start
from ..payments.stripe import stripe_start

from .forms import TicketPaymentForm, TicketPaymentShippingForm
from . import tickets, price_changed, empty_baskets, get_product_view


@tickets.route("/tickets/pay", methods=["GET", "POST"])
@tickets.route("/tickets/pay/<flow>", methods=["GET", "POST"])
def pay(flow="main"):
    """
        The user is sent here once they've added tickets to their basket.
        This view collects users details, offers payment options, and then
        starts the correct payment flow in the payment app.
    """
    view = get_product_view(flow)

    if not view.is_accessible(current_user, session.get("ticket_voucher")):
        # It's likely the user had a voucher which has been used
        # This happens if they press the back button while at the payment stage.
        if current_user.is_authenticated:
            # Redirect user to their purchases page so they can see their
            # unpaid payment and retry it.
            return redirect(url_for("users.purchases"))
        else:
            abort(404)

    if request.form.get("change_currency") in ("GBP", "EUR"):
        currency = request.form.get("change_currency")
        app.logger.info("Updating currency to %s", currency)
        set_user_currency(currency)
        db.session.commit()

        return redirect(url_for(".pay", flow=flow))

    basket = Basket.from_session(current_user, get_user_currency())
    if not any(basket.values()):
        empty_baskets.inc()

        if current_user.is_authenticated:
            basket.load_purchases_from_db()

        if any(basket.values()):
            # We've lost the user's state, but we can still show them all
            # tickets they've reserved and let them empty their basket.
            flash(
                "Your browser doesn't seem to be storing cookies. This may break some parts of the site."
            )
            app.logger.warn(
                "Basket is empty, so showing reserved tickets (%s)",
                request.headers.get("User-Agent"),
            )

        else:
            app.logger.info("Basket is empty, redirecting back to choose tickets")
            if view.type == "tickets":
                flash("Please select at least one ticket to buy.")
            elif view.type == "hire":
                flash("Please select at least one item to hire.")
            else:
                flash("Please select at least one item to buy.")
            return redirect(url_for("tickets.main", flow=flow))

    if basket.requires_shipping:
        if current_user.is_authenticated:
            shipping = current_user.shipping
        else:
            shipping = None

        form = TicketPaymentShippingForm(obj=shipping)
    else:
        form = TicketPaymentForm()

    form.flow = flow

    if current_user.is_authenticated:
        form.name.data = current_user.name
        del form.email
        if current_user.name != current_user.email and not basket.requires_shipping:
            # FIXME: is this helpful?
            del form.name

    if form.validate_on_submit():
        # Valid form submitted, process it
        return start_payment(form, basket, flow)

    form.basket_total.data = basket.total

    return render_template(
        "tickets/payment-choose.html",
        form=form,
        basket=basket,
        total=basket.total,
        flow=flow,
        view=view,
    )


def start_payment(form, basket, flow):
    if Decimal(form.basket_total.data) != Decimal(basket.total):
        # Check that the user's basket approximately matches what we told them they were paying.
        price_changed.inc()
        app.logger.warn(
            "User's basket has changed value %s -> %s",
            form.basket_total.data,
            basket.total,
        )
        flash(
            """The items you selected have changed, possibly because you had two windows open.
              Please verify that you've selected the correct items."""
        )
        return redirect(url_for("tickets.pay", flow=flow))

    user = current_user

    if user.is_anonymous:
        try:
            new_user = create_current_user(form.email.data, form.name.data)
        except IntegrityError as e:
            app.logger.warn("Adding user raised %r, possible double-click", e)
            return redirect(url_for("tickets.pay", flow=flow))

        user = new_user
    elif user.name == user.email:
        user.name = form.name.data

    if form.allow_promo.data:
        user.promo_opt_in = True

    if basket.requires_shipping:
        if not user.shipping:
            user.shipping = UserShipping()

        user.shipping.address_1 = form.address_1.data
        user.shipping.address_2 = form.address_2.data
        user.shipping.town = form.town.data
        user.shipping.postcode = form.postcode.data
        user.shipping.country = form.country.data

    payment_type = form.get_payment_class()

    basket.user = user
    payment = basket.create_payment(payment_type)
    basket.cancel_surplus_purchases()
    db.session.commit()

    Basket.clear_from_session()

    if not payment:
        empty_baskets.inc()
        app.logger.warn("User tried to pay for empty basket")
        flash(
            "We're sorry, your session information has been lost. Please try ordering again."
        )
        return redirect(url_for("tickets.main", flow=flow))

    if payment_type == GoCardlessPayment:
        return gocardless_start(payment)
    elif payment_type == BankPayment:
        return transfer_start(payment)
    elif payment_type == StripePayment:
        return stripe_start(payment)
