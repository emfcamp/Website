"""Payment handler for Stripe payments.

This takes payments using Stripe's
[Payment Intents](https://stripe.com/docs/payments/payment-intents) API.
"""

import logging
from collections.abc import Callable
from typing import Any

import stripe
from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask import (
    current_app as app,
)
from flask.typing import ResponseValue
from flask_login import current_user, login_required
from flask_mailman import EmailMessage
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from wtforms import SubmitField

from apps.payments.common import lock_user_payment_or_abort
from main import db, get_stripe_client
from models.payment import StripePayment

from ..common import feature_enabled
from ..common.email import from_email
from ..common.forms import Form
from ..common.receipt import attach_tickets, set_tickets_emailed
from . import payments, ticket_admin_email

logger = logging.getLogger(__name__)


class StripeUpdateUnexpected(Exception):
    pass


class StripeUpdateConflict(Exception):
    pass


webhook_handlers: dict[str | None, Callable[[str, Any], ResponseValue]] = {}


def webhook(type=None):
    def inner(f):
        webhook_handlers[type] = f
        return f

    return inner


def stripe_start(payment: StripePayment) -> ResponseValue:
    """This is called by the ticket flow to initialise the payment and
    redirect to the capture page. We don't need to do anything here."""
    logger.info("Starting Stripe payment %s", payment.id)
    db.session.commit()

    return redirect(url_for("payments.stripe_capture", payment_id=payment.id))


@payments.route("/pay/stripe/<int:payment_id>/capture")
@login_required
def stripe_capture(payment_id: int) -> ResponseValue:
    """This endpoint displays the card payment form, including the Stripe payment element.
    Card details are validated and submitted to Stripe by XHR, and the user is then sent by
    Stripe to the `stripe_waiting` endpoint.
    """
    payment = lock_user_payment_or_abort(payment_id, "stripe", valid_states=["new"])
    assert isinstance(payment, StripePayment)

    if not feature_enabled("STRIPE"):
        logger.warning("Unable to capture payment as Stripe is disabled")
        flash("Card payments are currently unavailable. Please try again later")
        return redirect(url_for("users.purchases"))
    stripe_client = get_stripe_client(app.config)

    if payment.intent_id is None:
        # Create the payment intent with Stripe. This intent will persist across retries.
        intent = stripe_client.v1.payment_intents.create(
            params={
                "amount": payment.amount_int,
                "currency": payment.currency.upper(),
                "metadata": {"user_id": str(current_user.id), "payment_id": str(payment.id)},
            },
        )
        payment.intent_id = intent.id
        db.session.commit()
    else:
        # Reuse a previously-created payment intent
        intent = stripe_client.v1.payment_intents.retrieve(payment.intent_id)
        if intent.status == "succeeded":
            logger.warning("Intent already succeeded, not capturing again")
            stripe_update_payment(stripe_client, payment, intent)
            return redirect(url_for(".stripe_waiting", payment_id=payment_id))

        if intent.payment_method:
            logger.warning(
                f"Intent already has payment method {intent.payment_method}, this will likely fail"
            )

    logger.info(
        "Starting checkout for Stripe payment %s with intent %s",
        payment.id,
        payment.intent_id,
    )
    return render_template(
        "payments/stripe-checkout.html",
        payment=payment,
        client_secret=intent.client_secret,
    )


class StripeCancelForm(Form):
    yes = SubmitField("Cancel payment")


@payments.route("/pay/stripe/<int:payment_id>/cancel", methods=["GET", "POST"])
@login_required
def stripe_cancel(payment_id: int) -> ResponseValue:
    payment = lock_user_payment_or_abort(payment_id, "stripe", valid_states=["new", "captured", "failed"])
    assert isinstance(payment, StripePayment)

    form = StripeCancelForm()
    if form.validate_on_submit():
        if form.yes.data:
            logger.info("Cancelling Stripe payment %s", payment.id)
            payment.cancel()
            db.session.commit()

            logger.info("Payment %s cancelled", payment.id)
            flash("Payment cancelled")

        return redirect(url_for("users.purchases"))

    return render_template("payments/stripe-cancel.html", payment=payment, form=form)


@payments.route("/pay/stripe/<int:payment_id>/waiting")
@login_required
def stripe_waiting(payment_id: int) -> ResponseValue:
    payment = lock_user_payment_or_abort(payment_id, "stripe", valid_states=["new", "paid"])
    assert isinstance(payment, StripePayment)

    if payment.state != "paid":
        stripe_client = get_stripe_client(app.config)
        stripe_update_payment(stripe_client, payment)

    if payment.state == "new":
        # Async payment failure. Redirect back to capture page.
        # This flow can be tested by choosing "pay by bank" and closing the popup
        flash("Your payment has not been completed - please try again.")
        return redirect(url_for(".stripe_capture", payment_id=payment_id))

    return render_template(
        "payments/stripe-waiting.html",
        payment=payment,
        days=app.config["EXPIRY_DAYS_STRIPE"],
    )


@payments.route("/stripe-webhook", methods=["POST"])
def stripe_webhook() -> ResponseValue:
    stripe_client = get_stripe_client(app.config)

    webhook_key = app.config.get("STRIPE_WEBHOOK_KEY")
    if webhook_key is None:
        logger.error("Stripe webhook received but no STRIPE_WEBHOOK_KEY set.")
        abort(500)

    try:
        event = stripe_client.construct_event(
            request.data,
            request.headers["STRIPE_SIGNATURE"],
            webhook_key,
        )
    except ValueError:
        logger.exception("Error decoding Stripe webhook")
        abort(400)
    except stripe.SignatureVerificationError:
        logger.exception("Error verifying Stripe webhook signature")
        abort(400)

    try:
        livemode = app.config.get("STRIPE_LIVEMODE", not app.config["DEBUG"])
        if event.livemode != livemode:
            logger.error("Unexpected livemode status %s, failing", event.livemode)
            abort(409)

        try:
            handler = webhook_handlers[event.type]
        except KeyError:
            handler = webhook_handlers[None]

        # Stripe's library seems to suggest that event.data.object here is dict[str, Any],
        # but it's actually a dict-derived object I think, so I've left the type here as Any.
        return handler(event.type, event.data.object)
    except Exception:
        logger.exception("Unhandled exception during Stripe webhook")
        logger.info("Webhook data: %s", request.data)
        abort(500)


@webhook()
def stripe_default(_type: str, _obj: Any) -> ResponseValue:
    """Default webhook handler"""
    return ""


@webhook("ping")
def stripe_ping(_type: str, _obj: Any) -> ResponseValue:
    return ""


def stripe_update_payment(
    stripe_client: stripe.StripeClient,
    payment: StripePayment,
    intent: stripe.PaymentIntent | None = None,
) -> None:
    """Update a Stripe payment.
    If a PaymentIntent object is not passed in, this will fetch the payment details from
    the Stripe API.
    """
    if payment.intent_id is None:
        raise ValueError("Payment intent_id is None")
    intent_is_fresh = False
    if intent is None:
        intent = stripe_client.v1.payment_intents.retrieve(
            payment.intent_id, params={"expand": ["latest_charge"]}
        )
        intent_is_fresh = True

    if intent.latest_charge is None:
        # Intent does not have a charge (yet?), do nothing
        return None

    if isinstance(intent.latest_charge, stripe.Charge):
        # The payment intent object has been expanded already
        charge = intent.latest_charge
    else:
        charge = stripe_client.v1.charges.retrieve(intent.latest_charge)

    if payment.charge_id is not None and payment.charge_id != charge.id:
        # The payment's failed and been retried, and this might be a
        # delayed webhook notification for the old charge ID. So we
        # need to check whether it's the latest.
        if intent_is_fresh:
            fresh_intent = intent
        else:
            fresh_intent = stripe_client.v1.payment_intents.retrieve(
                payment.intent_id, params={"expand": ["latest_charge"]}
            )

        if fresh_intent.latest_charge == charge.id:
            logger.warning(
                f"Charge ID for intent {intent.id} has changed from {payment.charge_id} to {charge.id}"
            )
        else:
            logger.warning(f"Charge ID {charge.id} for intent {intent.id} is out of date, ignoring")
            return None

    payment.charge_id = charge.id

    if charge.refunded:
        return stripe_payment_refunded(payment)
    if charge.paid:
        return stripe_payment_paid(payment)
    if charge.status == "failed":
        return stripe_payment_failed(payment)

    raise StripeUpdateUnexpected("Charge object is not paid, refunded or failed")


def stripe_payment_paid(payment: StripePayment) -> None:
    if payment.state == "paid":
        return

    if payment.state == "partrefunded":
        logger.info("Payment is already partially refunded, ignoring")
        return

    logger.info("Setting payment %s to paid", payment.id)
    payment.paid()
    db.session.commit()

    msg = EmailMessage(
        "Your EMF payment has been confirmed",
        from_email=from_email("TICKETS_EMAIL"),
        to=[payment.user.email],
    )

    already_emailed = set_tickets_emailed(payment.user)
    msg.body = render_template(
        "emails/payment-paid.txt",
        user=payment.user,
        payment=payment,
        already_emailed=already_emailed,
    )

    if feature_enabled("ISSUE_TICKETS"):
        attach_tickets(msg, payment.user)

    msg.send()
    db.session.commit()


def stripe_payment_refunded(payment: StripePayment) -> None:
    if payment.state in ("refunded", "refunding"):
        logger.info(f"Payment {payment.id} is {payment.state}, ignoring refund webhook")
        return

    logger.info("Setting payment %s to refunded", payment.id)

    # Payment is already locked by the caller of stripe_update_payment
    with db.session.no_autoflush:
        for purchase in payment.purchases:
            purchase.refund_purchase()

    payment.state = "refunded"
    db.session.commit()

    ticket_admin_email(
        "Unexpected Stripe refund received",
        "emails/notice-payment-refunded.txt",
        payment=payment,
    )


def stripe_payment_part_refunded(payment: StripePayment) -> None:
    # Payments can be marked as "refunded" if the user has requested a full refund with
    # donation. This is a part-refund on Stripe's end.
    if payment.state in ("partrefunded", "refunded", "refunding"):
        logger.info(f"Payment {payment.id} is {payment.state}, ignoring part-refund webhook")
        return

    ticket_admin_email(
        "Unexpected Stripe part-refund received",
        "emails/notice-payment-refunded.txt",
        payment=payment,
    )


def stripe_payment_failed(payment: StripePayment) -> None:
    # Stripe payments almost always fail during capture, which will result in an immediate
    # error on the capture page. In some cases the Stripe element fails (this can be
    # reproduced by choosing "pay by bank" and closing the popup), and we leave the payment
    # state as "new" so it can be retried.
    if payment.state == "partrefunded":
        logger.error("Payment is already partially refunded, so cannot be failed")
        raise StripeUpdateConflict()

    if payment.state == "paid":
        logger.error("Failed notification for paid charge")
        raise StripeUpdateConflict()

    # A failed payment can be retried by revisiting the capture page, so we don't want
    # to set the payment state to failed here.


def lock_payment_or_abort_by_intent(intent_id: str) -> StripePayment:
    try:
        return db.session.execute(
            select(StripePayment).where(StripePayment.intent_id == intent_id).with_for_update()
        ).scalar_one()
    except NoResultFound:
        logger.error("Payment for intent %s not found", intent_id)
        abort(409)


def lock_payment_or_abort_by_charge(charge_id: str) -> StripePayment:
    try:
        return db.session.execute(
            select(StripePayment).where(StripePayment.charge_id == charge_id).with_for_update()
        ).scalar_one()
    except NoResultFound:
        logger.error("Payment for charge %s not found", charge_id)
        abort(409)


@webhook("payment_intent.canceled")
@webhook("payment_intent.created")
@webhook("payment_intent.payment_failed")
@webhook("payment_intent.succeeded")
def stripe_payment_intent_updated(hook_type: str, intent: Any) -> ResponseValue:
    payment = lock_payment_or_abort_by_intent(intent.id)

    logger.info(
        "Received %s message for intent %s, payment %s",
        hook_type,
        intent.id,
        payment.id,
    )

    stripe_client = get_stripe_client(app.config)
    try:
        stripe_update_payment(stripe_client, payment, intent)
    except StripeUpdateConflict:
        abort(409)
    except StripeUpdateUnexpected:
        abort(501)

    return ""


@webhook("charge.refunded")
def stripe_charge_refunded(_type: str, charge: Any) -> ResponseValue:
    payment = lock_payment_or_abort_by_charge(charge.id)

    logger.info(
        "Received charge.refunded message for charge %s, payment %s",
        charge.id,
        payment.id,
    )

    if charge.amount == charge.amount_refunded:
        # Full refund
        stripe_payment_refunded(payment)
    else:
        stripe_payment_part_refunded(payment)

    return ""


def stripe_validate():
    """Validate Stripe is configured and operational"""
    result = []
    sk = app.config.get("STRIPE_SECRET_KEY", "")
    if len(sk) > 15 and sk.startswith("sk_"):
        if sk.startswith("sk_test"):
            result.append((True, "Secret key configured (TEST MODE)"))
        else:
            result.append((True, "Secret key configured"))
    else:
        result.append((False, "Secret key not configured"))

    pk = app.config.get("STRIPE_PUBLIC_KEY", "")
    if len(pk) > 15 and pk.startswith("pk_"):
        if pk.startswith("pk_test"):
            result.append((True, "Public key configured (TEST MODE)"))
        else:
            result.append((True, "Public key configured"))
    else:
        result.append((False, "Public key not configured"))

    whk = app.config.get("STRIPE_WEBHOOK_KEY", "")
    if len(whk) > 15 and whk.startswith("whsec_"):
        result.append((True, "Webhook key configured"))
    else:
        result.append((False, "Webhook key not configured"))

    stripe_client = get_stripe_client(app.config)
    try:
        webhooks = stripe_client.v1.webhook_endpoints.list()
        result.append((True, "Connection to Stripe API succeeded"))
    except stripe.AuthenticationError as e:
        result.append((False, f"Connecting to Stripe failed: {e}"))
        return result

    if len(webhooks) > 0:
        webhook_urls = " ".join(webhook["url"] for webhook in webhooks)
        result.append((True, f"{len(webhooks)} webhook(s) configured: {webhook_urls}"))
        for webhook in webhooks:
            if webhook["status"] != "enabled":
                result.append((False, f"Webhook {webhook['url']} is {webhook['status']}"))

            not_found = 0
            for event in webhook_handlers:
                if event not in webhook.enabled_events:
                    if event in {None, 'ping'}:
                        continue
                    not_found += 1
                    result.append((False, f"Webhook endpoint {webhook['url']} is not configured to deliver the {event} event"))
            if not_found == 0:
                result.append((True, f"Webhook endpoint {webhook['url']} is configured to deliver all required events"))
    else:
        result.append((False, "No webhooks configured"))

    return result
