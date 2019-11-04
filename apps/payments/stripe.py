""" Payment handler for Stripe credit card payments.

    This takes credit card payments using Stripe's
    [Payment Intents](https://stripe.com/docs/payments/payment-intents) API.

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
from flask_mail import Message
from wtforms import SubmitField, StringField
from sqlalchemy.orm.exc import NoResultFound

from main import db, stripe, mail, csrf
from models import RefundRequest
from models.payment import StripePayment
from ..common import feature_enabled, feature_flag
from ..common.forms import Form
from ..common.receipt import attach_tickets, set_tickets_emailed
from . import get_user_payment_or_abort, lock_user_payment_or_abort
from . import payments

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


def stripe_start(payment):
    logger.info("Created Stripe payment %s", payment.id)
    db.session.commit()

    return redirect(url_for("payments.stripe_capture", payment_id=payment.id))


@payments.route("/pay/stripe/<int:payment_id>/capture")
@login_required
def stripe_capture(payment_id):
    """ This endpoint displays the card payment form, including the Stripe payment element.
        Card details are validated and submitted to Stripe by XHR, and if it succeeds
        a POST is sent back, which is received by the next endpoint.
    """
    payment = lock_user_payment_or_abort(payment_id, "stripe", valid_states=["new"])

    if not feature_enabled("STRIPE"):
        logger.warn("Unable to capture payment as Stripe is disabled")
        flash("Card payments are currently unavailable. Please try again later")
        return redirect(url_for("users.purchases"))

    if payment.intent_id is None:
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

    logger.info(
        "Starting checkout for payment %s with intent %s", payment.id, payment.intent_id
    )
    return render_template(
        "payments/stripe-checkout.html",
        payment=payment,
        client_secret=intent.client_secret,
    )


@payments.route("/pay/stripe/<int:payment_id>/capture", methods=["POST"])
@login_required
def stripe_capture_post(payment_id):
    payment = lock_user_payment_or_abort(payment_id, "stripe")
    if payment.state == "new":
        payment.state = "charged"
        db.session.commit()
    return redirect(url_for(".stripe_waiting", payment_id=payment_id))


class StripeChargeAgainForm(Form):
    tryagain = SubmitField("Try again")
    cancel = SubmitField("Cancel")


@payments.route("/pay/stripe/<int:payment_id>/tryagain", methods=["GET", "POST"])
@login_required
def stripe_tryagain(payment_id):
    payment = lock_user_payment_or_abort(
        payment_id,
        "stripe",
        valid_states=["new", "captured"],  # once it's charging/charged it's too late
    )

    if not feature_enabled("STRIPE"):
        logger.warn("Unable to retry payment as Stripe is disabled")
        flash("Stripe is currently unavailable. Please try again later")
        return redirect(url_for("users.purchases"))

    if payment.state == "new":
        return redirect(url_for(".stripe_capture", payment_id=payment.id))

    form = StripeChargeAgainForm()
    if form.validate_on_submit():
        if form.tryagain.data:
            logger.info("Trying to charge payment %s again", payment.id)
            return redirect(url_for(".stripe_waiting", payment_id=payment.id))
        elif form.cancel.data:
            payment.cancel()
            db.session.commit()
            flash("Your payment has been cancelled. Please place your order again.")
            return redirect(url_for("tickets.main"))

    return render_template("payments/stripe-tryagain.html", payment=payment, form=form)


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
        payment_id, "stripe", valid_states=["charged", "paid"]
    )
    return render_template(
        "payments/stripe-waiting.html",
        payment=payment,
        days=app.config["EXPIRY_DAYS_STRIPE"],
    )


class StripeRefundForm(Form):
    note = StringField("Note")
    yes = SubmitField("Request refund")


@payments.route("/pay/stripe/<int:payment_id>/refund", methods=["GET", "POST"])
@login_required
@feature_flag("REFUND_REQUESTS")
def stripe_refund_start(payment_id):
    payment = get_user_payment_or_abort(payment_id, "stripe", valid_states=["paid"])

    form = StripeRefundForm()

    if form.validate_on_submit():
        app.logger.info("Creating refund request for Stripe payment %s", payment.id)
        req = RefundRequest(payment=payment, note=form.note.data)
        db.session.add(req)
        payment.state = "refund-requested"

        if not app.config.get("TICKETS_NOTICE_EMAIL"):
            app.logger.warning("No tickets notice email configured, not sending")

        else:
            msg = Message(
                "An EMF refund request has been received",
                sender=app.config.get("TICKETS_EMAIL"),
                recipients=[app.config.get("TICKETS_NOTICE_EMAIL")[1]],
            )
            msg.body = render_template(
                "emails/notice-refund-request.txt", payment=payment
            )
            mail.send(msg)

        db.session.commit()

        flash("Your refund request has been sent")
        return redirect(url_for("users.purchases"))

    return render_template("payments/stripe-refund.html", payment=payment, form=form)


@csrf.exempt
@payments.route("/stripe-webhook", methods=["POST"])
def stripe_webhook():
    try:
        event = stripe.Webhook.construct_event(
            request.data,
            request.headers["STRIPE_SIGNATURE"],
            app.config.get("STRIPE_WEBHOOK_KEY"),
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        abort(400)

    try:
        livemode = not app.config.get("DEBUG")
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
def stripe_default(type, obj_data):
    # We can fetch events with Event.all for 30 days
    return ("", 200)


@webhook("ping")
def stripe_ping(type, ping_data):
    return ("", 200)


def stripe_update_payment(payment: StripePayment, intent: stripe.PaymentIntent = None):
    """ Update a Stripe payment.
        If a PaymentIntent object is not passed in, this will fetch the payment details from the Stripe API.
    """
    if intent is None:
        intent = stripe.PaymentIntent.retrieve(payment.intent_id)

    if len(intent.charges) == 0:
        # Intent does not have a charge (yet?), do nothing
        return
    elif len(intent.charges) > 1:
        app.logger.error(f"Payment intent #{intent['id']} has more than one charge")
        raise StripeUpdateUnexpected()

    charge = intent.charges.data[0]

    if payment.charge_id is None:
        payment.charge_id = charge["id"]

    if payment.charge_id != charge["id"]:
        app.logger.error(
            f"Charge ID for intent #{intent['id']} has changed from #{payment.charge_id} to #{charge['id']}"
        )
        raise StripeUpdateUnexpected()

    if charge.refunded:
        return stripe_payment_refunded(payment)
    elif charge.status == "succeeded":
        return stripe_payment_paid(payment)
    elif charge.status == "failed":
        return stripe_payment_failed(payment)

    app.logger.error("Charge object is not paid, refunded or failed")
    raise StripeUpdateUnexpected()


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

    msg = Message(
        "Your EMF payment has been confirmed",
        sender=app.config.get("TICKETS_EMAIL"),
        recipients=[payment.user.email],
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

    mail.send(msg)
    db.session.commit()


def stripe_payment_refunded(payment: StripePayment):
    if payment.state == "refunded":
        logger.info("Payment is already refunded, ignoring")
        return

    logger.info("Setting payment %s to refunded", payment.id)

    # Payment is already locked by the caller of stripe_update_payment
    with db.session.no_autoflush:
        for purchase in payment.purchases:
            purchase.refund_purchase()

    payment.state = "refunded"
    db.session.commit()

    if not app.config.get("TICKETS_NOTICE_EMAIL"):
        app.logger.warning("No tickets notice email configured, not sending")
        return

    msg = Message(
        "An EMF payment has been refunded",
        sender=app.config.get("TICKETS_EMAIL"),
        recipients=[app.config.get("TICKETS_NOTICE_EMAIL")[1]],
    )
    msg.body = render_template("emails/notice-payment-refunded.txt", payment=payment)
    mail.send(msg)


def stripe_payment_failed(payment):
    # Stripe payments almost always fail during capture, but can be failed while charging.
    # Test with 4000 0000 0000 0341
    if payment.state == "failed":
        return

    if payment.state == "partrefunded":
        logger.error("Payment is already partially refunded, so cannot be failed")
        raise StripeUpdateConflict()

    if payment.state == "paid":
        logger.error("Failed notification for paid charge")
        raise StripeUpdateConflict()

    # A failed payment can be retried by revisiting the capture page, so we don't want
    # to set the payment state to failed here.


def lock_payment_or_abort(intent_id):
    try:
        return (
            StripePayment.query.filter_by(intent_id=intent_id).with_for_update().one()
        )
    except NoResultFound:
        logger.error("Payment for intent %s not found", intent_id)
        abort(409)


@webhook("payment_intent.canceled")
@webhook("payment_intent.created")
@webhook("payment_intent.payment_failed")
@webhook("payment_intent.succeeded")
def stripe_payment_intent_updated(type, intent):
    payment = lock_payment_or_abort(intent.id)

    logger.info(
        "Received %s message for intent %s, payment %s", type, intent.id, payment.id
    )

    try:
        stripe_update_payment(payment, intent)
    except StripeUpdateConflict:
        abort(409)
    except StripeUpdateUnexpected:
        abort(501)

    return ("", 200)
