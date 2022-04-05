""" Payment handler for Stripe credit card payments.

    This takes credit card payments using Stripe's
    [Payment Intents](https://stripe.com/docs/payments/payment-intents) API.

    In theory we could use this handler to take payments for other methods which
    Stripe supports, such as iDEAL. However, Payment Intents doesn't support these
    (as of Nov 2019), so it would involve using a different flow which would
    complicate this code.
"""
import logging

from flask import (
    render_template,
    redirect,
    request,
    flash,
    url_for,
    abort,
    current_app as app,
)
from flask_login import login_required, current_user
from flask_mailman import EmailMessage
from wtforms import SubmitField
from sqlalchemy.orm.exc import NoResultFound
from stripe.error import AuthenticationError

from main import db, stripe
from models.payment import StripePayment
from ..common import feature_enabled
from ..common.email import from_email
from ..common.forms import Form
from ..common.receipt import attach_tickets, set_tickets_emailed
from . import get_user_payment_or_abort, lock_user_payment_or_abort
from . import payments, ticket_admin_email

logger = logging.getLogger(__name__)


class StripeUpdateUnexpected(Exception):
    pass


class StripeUpdateConflict(Exception):
    pass


webhook_handlers = {}


def webhook(type=None):
    def inner(f):
        webhook_handlers[type] = f
        return f

    return inner


def stripe_start(payment: StripePayment):
    """This is called by the ticket flow to initialise the payment and
    redirect to the capture page. We don't need to do anything here."""
    logger.info("Starting Stripe payment %s", payment.id)
    db.session.commit()

    return redirect(url_for("payments.stripe_capture", payment_id=payment.id))


@payments.route("/pay/stripe/<int:payment_id>/capture")
@login_required
def stripe_capture(payment_id):
    """This endpoint displays the card payment form, including the Stripe payment element.
    Card details are validated and submitted to Stripe by XHR, and if it succeeds
    a POST is sent back, which is received by the next endpoint.
    """
    payment = lock_user_payment_or_abort(payment_id, "stripe", valid_states=["new"])

    if not feature_enabled("STRIPE"):
        logger.warn("Unable to capture payment as Stripe is disabled")
        flash("Card payments are currently unavailable. Please try again later")
        return redirect(url_for("users.purchases"))

    if payment.intent_id is None:
        # Create the payment intent with Stripe. This intent will persist across retries.
        intent = stripe.PaymentIntent.create(
            amount=payment.amount_int,
            currency=payment.currency.upper(),
            statement_descriptor_suffix=payment.description,
            metadata={"user_id": current_user.id, "payment_id": payment.id},
        )
        payment.intent_id = intent.id
        db.session.commit()
    else:
        # Reuse a previously-created payment intent
        intent = stripe.PaymentIntent.retrieve(payment.intent_id)
        if intent.status == "succeeded":
            logger.warn(f"Intent already succeeded, not capturing again")
            payment.state = "charging"
            db.session.commit()
            return redirect(url_for(".stripe_waiting", payment_id=payment_id))

        if intent.payment_method:
            logger.warn(
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


@payments.route("/pay/stripe/<int:payment_id>/capture", methods=["POST"])
@login_required
def stripe_capture_post(payment_id):
    """The user is sent here after the payment has succeeded in the browser.
    We set the payment state to charging, but we're expecting a webhook to
    set it to "paid" almost immediately.
    """
    payment = lock_user_payment_or_abort(payment_id, "stripe")
    if payment.state == "new":
        payment.state = "charging"
        db.session.commit()
    return redirect(url_for(".stripe_waiting", payment_id=payment_id))


class StripeCancelForm(Form):
    yes = SubmitField("Cancel payment")


@payments.route("/pay/stripe/<int:payment_id>/cancel", methods=["GET", "POST"])
@login_required
def stripe_cancel(payment_id):
    payment = lock_user_payment_or_abort(
        payment_id, "stripe", valid_states=["new", "captured", "failed"]
    )

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
def stripe_waiting(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, "stripe", valid_states=["charging", "paid"]
    )
    return render_template(
        "payments/stripe-waiting.html",
        payment=payment,
        days=app.config["EXPIRY_DAYS_STRIPE"],
    )


@payments.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    try:
        event = stripe.Webhook.construct_event(
            request.data,
            request.headers["STRIPE_SIGNATURE"],
            app.config.get("STRIPE_WEBHOOK_KEY"),
        )
    except ValueError:
        logger.exception("Error decoding Stripe webhook")
        abort(400)
    except stripe.error.SignatureVerificationError:
        logger.exception("Error verifying Stripe webhook signature")
        abort(400)

    try:
        livemode = app.config.get("STRIPE_LIVEMODE", not app.config["DEBUG"])
        if event.livemode != livemode:
            logger.error("Unexpected livemode status %s, failing", event.livemode)
            abort(409)

        try:
            handler = webhook_handlers[event.type]
        except KeyError as e:
            handler = webhook_handlers[None]

        return handler(event.type, event.data.object)
    except Exception as e:
        logger.exception("Unhandled exception during Stripe webhook")
        logger.info("Webhook data: %s", request.data)
        abort(500)


@webhook()
def stripe_default(_type, _obj):
    """Default webhook handler"""
    return ("", 200)


@webhook("ping")
def stripe_ping(_type, _obj):
    return ("", 200)


def stripe_update_payment(payment: StripePayment, intent: stripe.PaymentIntent = None):
    """Update a Stripe payment.
    If a PaymentIntent object is not passed in, this will fetch the payment details from the Stripe API.
    """
    if intent is None:
        intent = stripe.PaymentIntent.retrieve(payment.intent_id)

    if len(intent.charges) == 0:
        # Intent does not have a charge (yet?), do nothing
        return
    elif len(intent.charges) > 1:
        raise StripeUpdateUnexpected(
            f"Payment intent #{intent['id']} has more than one charge"
        )

    charge = intent.charges.data[0]

    if payment.charge_id is not None and payment.charge_id != charge["id"]:
        logger.warn(
            f"Charge ID for intent {intent['id']} has changed from {payment.charge_id} to {charge['id']}"
        )

    payment.charge_id = charge["id"]

    if charge.refunded:
        return stripe_payment_refunded(payment)
    elif charge.paid:
        return stripe_payment_paid(payment)
    elif charge.status == "failed":
        return stripe_payment_failed(payment)

    logger.error(f"Charge is {charge.status}, expected refunded, paid or failed")
    raise StripeUpdateUnexpected("Charge object is not refunded, paid or failed")


def stripe_payment_paid(payment: StripePayment):
    if payment.state == "paid":
        logger.info("Payment is already paid, ignoring")
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
        "emails/tickets-paid-email-stripe.txt",
        user=payment.user,
        payment=payment,
        already_emailed=already_emailed,
    )

    if feature_enabled("ISSUE_TICKETS"):
        attach_tickets(msg, payment.user)

    msg.send()
    db.session.commit()


def stripe_payment_refunded(payment: StripePayment):
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


def stripe_payment_part_refunded(payment: StripePayment, charge):
    # Payments can be marked as "refunded" if the user has requested a full refund with
    # donation. This is a part-refund on Stripe's end.
    if payment.state in ("partrefunded", "refunded", "refunding"):
        logger.info(
            f"Payment {payment.id} is {payment.state}, ignoring part-refund webhook"
        )
        return

    ticket_admin_email(
        "Unexpected Stripe part-refund received",
        "emails/notice-payment-refunded.txt",
        payment=payment,
    )


def stripe_payment_failed(payment):
    # Stripe payments almost always fail during capture, but can be failed while charging.
    # Test with 4000 0000 0000 0341
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
        return (
            StripePayment.query.filter_by(intent_id=intent_id).with_for_update().one()
        )
    except NoResultFound:
        logger.error("Payment for intent %s not found", intent_id)
        abort(409)


def lock_payment_or_abort_by_charge(charge_id: str) -> StripePayment:
    try:
        return (
            StripePayment.query.filter_by(charge_id=charge_id).with_for_update().one()
        )
    except NoResultFound:
        logger.error("Payment for charge %s not found", charge_id)
        abort(409)


@webhook("payment_intent.canceled")
@webhook("payment_intent.created")
@webhook("payment_intent.payment_failed")
@webhook("payment_intent.succeeded")
def stripe_payment_intent_updated(hook_type, intent):
    payment = lock_payment_or_abort_by_intent(intent.id)

    logger.info(
        "Received %s message for intent %s, payment %s",
        hook_type,
        intent.id,
        payment.id,
    )

    try:
        stripe_update_payment(payment, intent)
    except StripeUpdateConflict:
        abort(409)
    except StripeUpdateUnexpected:
        abort(501)

    return ("", 200)


@webhook("charge.refunded")
def stripe_charge_refunded(_type, charge):
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
        stripe_payment_part_refunded(payment, charge)

    return ("", 200)


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

    try:
        webhooks = stripe.WebhookEndpoint.list()
        result.append((True, "Connection to Stripe API succeeded"))
    except AuthenticationError as e:
        result.append((False, f"Connecting to Stripe failed: {e}"))
        return result

    if len(webhooks) > 0:
        webhook_urls = " ".join(webhook["url"] for webhook in webhooks)
        result.append((True, f"{len(webhooks)} webhook(s) configured: {webhook_urls}"))
        for webhook in webhooks:
            if webhook["status"] != "enabled":
                result.append(
                    (False, f"Webhook {webhook['url']} is {webhook['status']}")
                )
    else:
        result.append((False, "No webhooks configured"))

    return result
