import simplejson
import logging
from datetime import datetime, timedelta

from flask import (
    render_template,
    redirect,
    request,
    flash,
    url_for,
    abort,
    current_app as app,
)
from flask_login import login_required
from flask_mail import Message
from wtforms import SubmitField, HiddenField, StringField
from sqlalchemy.orm.exc import NoResultFound

from main import db, stripe, mail, csrf
from models import RefundRequest
from models.payment import StripePayment
from models.site_state import event_start
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


def charge_stripe(payment):
    logger.info("Charging Stripe payment %s, token %s", payment.id, payment.token)
    # If we fail to go from charging to charged, we won't have the charge ID,
    # so can't process the webhook. The payment will need to be manually resolved.
    # Test this with 4000000000000341.

    payment.state = "charging"
    db.session.commit()
    payment = get_user_payment_or_abort(payment.id, "stripe", valid_states=["charging"])

    # Stripe say it's max 15 chars, appended to company name,
    # but it looks like only 10 chars is reliable.
    description = "EMF {}".format(event_start().year)
    try:
        try:
            charge = stripe.Charge.create(
                amount=payment.amount_int,
                currency=payment.currency.lower(),
                card=payment.token,
                description=payment.description,
                statement_description=description,
            )
        except stripe.CardError as e:
            error = e.json_body["error"]
            logger.warn('Card payment failed with exception "%s"', e)
            flash(
                "Unfortunately your card payment failed with the error: %s"
                % (error["message"])
            )
            raise

        except Exception as e:
            logger.warn("Exception %r confirming payment", e)
            flash("An error occurred with your payment, please try again")
            raise

    except Exception:
        # Allow trying again
        payment.state = "captured"
        db.session.commit()
        return redirect(url_for(".stripe_tryagain", payment_id=payment.id))

    payment.chargeid = charge.id
    if charge.paid:
        payment.paid()
    else:
        payment.state = "charged"
        payment.expires = datetime.utcnow() + timedelta(
            days=app.config["EXPIRY_DAYS_STRIPE"]
        )

    db.session.commit()

    logger.info("Payment %s completed OK (state %s)", payment.id, payment.state)

    # FIXME: determine whether these are tickets or generic products
    msg = Message(
        "Your EMF ticket purchase",
        sender=app.config.get("TICKETS_EMAIL"),
        recipients=[payment.user.email],
    )

    already_emailed = set_tickets_emailed(payment.user)
    msg.body = render_template(
        "emails/tickets-purchased-email-stripe.txt",
        user=payment.user,
        payment=payment,
        already_emailed=already_emailed,
    )

    if feature_enabled("ISSUE_TICKETS") and charge.paid:
        attach_tickets(msg, payment.user)

    mail.send(msg)
    db.session.commit()

    return redirect(url_for(".stripe_waiting", payment_id=payment.id))


class StripeAuthorizeForm(Form):
    token = HiddenField("Stripe token")
    forward = SubmitField("Continue")


@payments.route("/pay/stripe/<int:payment_id>/capture", methods=["GET", "POST"])
@login_required
def stripe_capture(payment_id):
    payment = lock_user_payment_or_abort(payment_id, "stripe", valid_states=["new"])

    if not feature_enabled("STRIPE"):
        logger.warn("Unable to capture payment as Stripe is disabled")
        flash("Stripe is currently unavailable. Please try again later")
        return redirect(url_for("users.purchases"))

    form = StripeAuthorizeForm()
    if form.validate_on_submit():
        try:
            logger.info(
                "Stripe payment %s captured, token %s", payment.id, payment.token
            )
            payment.token = form.token.data
            payment.state = "captured"
            db.session.commit()

            payment = lock_user_payment_or_abort(
                payment_id, "stripe", valid_states=["captured"]
            )
        except Exception as e:
            logger.warn("Exception %r updating payment", e)
            flash("An error occurred with your payment, please try again")
            return redirect(url_for(".stripe_tryagain", payment_id=payment.id))

        return charge_stripe(payment)

    logger.info("Trying to check out payment %s", payment.id)
    return render_template("stripe-checkout.html", payment=payment, form=form)


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
            return charge_stripe(payment)
        elif form.cancel.data:
            payment.cancel()
            db.session.commit()
            flash("Your payment has been cancelled. Please place your order again.")
            return redirect(url_for("tickets.main"))

    return render_template("stripe-tryagain.html", payment=payment, form=form)


class StripeCancelForm(Form):
    yes = SubmitField("Cancel payment")


@payments.route("/pay/stripe/<int:payment_id>/cancel", methods=["GET", "POST"])
@login_required
def stripe_cancel(payment_id):
    payment = lock_user_payment_or_abort(
        payment_id, "stripe", valid_states=["new", "captured"]
    )

    form = StripeCancelForm()
    if form.validate_on_submit():
        if form.yes.data:
            logger.info("Cancelling Stripe payment %s", payment.id)
            payment.cancel()
            db.session.commit()

            if payment.token:
                logger.warn("Stripe payment has outstanding token %s", payment.token)

            logger.info("Payment %s cancelled", payment.id)
            flash("Payment cancelled")

        return redirect(url_for("users.purchases"))

    return render_template("stripe-cancel.html", payment=payment, form=form)


@payments.route("/pay/stripe/<int:payment_id>/waiting")
@login_required
def stripe_waiting(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, "stripe", valid_states=["charged", "paid"]
    )
    return render_template(
        "stripe-waiting.html", payment=payment, days=app.config["EXPIRY_DAYS_STRIPE"]
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
    logger.debug("Stripe webhook called with %s", request.data)
    json_data = simplejson.loads(request.data)

    try:
        if json_data["object"] != "event":
            logger.warning("Unrecognised callback object: %s", json_data["object"])
            abort(501)

        livemode = not app.config.get("DEBUG")
        if json_data["livemode"] != livemode:
            logger.error(
                "Unexpected livemode status %s, failing", json_data["livemode"]
            )
            abort(409)

        obj_data = json_data["data"]["object"]
        type = json_data["type"]
        try:
            handler = webhook_handlers[type]
        except KeyError as e:
            handler = webhook_handlers[None]

        return handler(type, obj_data)
    except Exception as e:
        logger.error("Unexcepted exception during webhook: %r", e)
        logger.info("Webhook data: %s", request.data)
        abort(500)


@webhook()
def stripe_default(type, obj_data):
    # We can fetch events with Event.all for 30 days
    logger.warn("Default handler called for %s: %s", type, obj_data)
    return ("", 200)


@webhook("ping")
def stripe_ping(type, ping_data):
    return ("", 200)


def lock_payment_or_abort(charge_id):
    try:
        return StripePayment.query.filter_by(chargeid=charge_id).with_for_update().one()
    except NoResultFound:
        logger.error("Payment for charge %s not found", charge_id)
        abort(409)


def stripe_update_payment(payment):
    charge = stripe.Charge.retrieve(payment.chargeid)
    if charge.refunded:
        return stripe_payment_refunded(payment)

    elif charge.paid:
        return stripe_payment_paid(payment)

    elif charge.failed:
        return stripe_payment_failed(payment)

    app.logger.error("Charge object is not paid, refunded or failed")
    raise StripeUpdateUnexpected()


def stripe_payment_paid(payment):
    if payment.state == "paid":
        logger.info("Payment is already paid, ignoring")
        return

    if payment.state == "partrefunded":
        logger.info("Payment is already partially refunded, ignoring")
        return

    if payment.state != "charged":
        logger.error("Current payment state is %s (should be charged)", payment.state)
        raise StripeUpdateConflict()

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


def stripe_payment_refunded(payment):
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
        logger.info("Payment is already failed, ignoring")
        return

    if payment.state == "partrefunded":
        logger.error("Payment is already partially refunded, so cannot be failed")
        raise StripeUpdateConflict()

    if payment.state != "charged":
        logger.error("Current payment state is %s (should be charged)", payment.state)
        raise StripeUpdateConflict()

    payment.state = "failed"
    db.session.commit()

    # Charge can be retried, so nothing else to do.


@webhook("charge.succeeded")
@webhook("charge.refunded")
@webhook("charge.updated")
@webhook("charge.failed")
def stripe_charge_updated(type, charge_data):
    payment = lock_payment_or_abort(charge_data["id"])

    logger.info(
        "Received %s message for charge %s, payment %s",
        type,
        charge_data["id"],
        payment.id,
    )

    try:
        stripe_update_payment(payment)
    except StripeUpdateConflict:
        abort(409)
    except StripeUpdateUnexpected:
        abort(501)

    return ("", 200)


@webhook("charge.dispute.created")
@webhook("charge.dispute.updated")
@webhook("charge.dispute.closed")
def stripe_dispute_update(type, dispute_data):
    payment = lock_payment_or_abort(dispute_data["charge"])
    logger.critical(
        "Unexpected charge dispute event %s for payment %s: %s",
        type,
        payment.id,
        dispute_data,
    )

    db.session.rollback()
    # Don't block other events
    return ("", 200)
