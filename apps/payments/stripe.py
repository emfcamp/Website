""" Payment handler for Stripe credit card payments.

    This takes credit card payments using Stripe's
    [Payment Intents](https://stripe.com/docs/payments/payment-intents) API.

    In theory we could use this handler to take payments for other methods which
    Stripe supports, such as iDEAL. However, Payment Intents doesn't support these
    (as of Nov 2019), so it would involve using a different flow which would
    complicate this code.
"""

import logging

from flask import render_template
from flask_mailman import EmailMessage

from main import db, stripe
from models.payment import StripePayment
from ..common import feature_enabled
from ..common.email import from_email
from ..common.receipt import attach_tickets, set_tickets_emailed
from . import ticket_admin_email

logger = logging.getLogger(__name__)


class StripeUpdateUnexpected(Exception):
    pass


class StripeUpdateConflict(Exception):
    pass


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

    raise StripeUpdateUnexpected("Charge object is not paid, refunded or failed")


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
        "emails/payment-paid.txt",
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
