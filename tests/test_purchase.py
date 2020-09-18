import pytest
import os.path
import json
import stripe
from flask_login import login_user

from models.basket import Basket
from models.product import PriceTier
from models.payment import StripePayment, RefundRequest

from apps.payments.stripe import (
    stripe_start,
    stripe_capture,
    stripe_capture_post,
    stripe_payment_intent_updated,
    stripe_charge_refunded,
)
from apps.payments.refund import handle_refund_request

from main import db


def load_webhook_fixture(name):
    fixture_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "webhook_fixtures", f"{name}.json"
    )
    with open(fixture_path, "r") as f:
        return stripe.Event.construct_from(json.load(f), None)


# This test uses VCR to automatically store Stripe responses as test fixtures.
# It also uses some webhook fixtures which we manually supply.
#
# Note that if you want to update the VCR fixtures, you'll need to temporarily add
# test Stripe credentials to test.cfg. Note that the IDs in the responses will need
# doctoring.
@pytest.mark.vcr()
def test_create_stripe_purchase(user, app, monkeypatch):
    # Add some tickets to a basket (/tickets/choose)
    basket = Basket(user, "GBP")
    tier = PriceTier.query.filter_by(name="full-std").one_or_none()
    basket[tier] = 2

    basket.create_purchases()
    basket.ensure_purchase_capacity()
    db.session.commit()

    # This matches the intent ID in stored fixtures
    intent_id = "pi_1GUslpIcI91cWsdeheAuRsyg"

    with app.test_request_context("/tickets/pay"):
        login_user(user)
        payment = basket.create_payment(StripePayment)
        stripe_start(payment)

    assert payment.state == "new"

    with app.test_request_context(f"/pay/stripe/{payment.id}/capture"):
        login_user(user)
        # Start capture process - this creates a payment intent from fake-stripe
        stripe_capture(payment.id)

        # A payment_intent.created webhook should be generated here, but it
        # doesn't cause any action on our end so we don't simulate this.
        assert payment.intent_id == intent_id
        assert payment.state == "new"

        # User is now on the Stripe form, which captures the card details.
        # Once this is complete, payment details are sent to Stripe and the form
        # submission triggers stripe_capture_post
        stripe_capture_post(payment.id)

    assert payment.state == "charging"

    with app.test_request_context("/stripe-webhook"):
        # Stripe will now send a webhook to notify us of the payment success.
        stripe_payment_intent_updated(
            "payment_intent.succeeded", load_webhook_fixture("payment_intent.succeeded")
        )
        # A charge.succeeded webhook is also sent but we ignore it.

    assert payment.state == "paid"
    assert all(
        purchase.state == "paid" for purchase in payment.purchases
    ), "Purchases should be marked as paid after payment"

    # Payment is all paid. Now we test refunding it.
    # Create a refund request for the entire payment, with £20 donation.
    refund_request = RefundRequest(
        payment=payment, donation=20, currency=payment.currency
    )
    payment.state = "refund-requested"
    db.session.add(refund_request)
    db.session.commit()

    handle_refund_request(refund_request)

    with app.test_request_context("/stripe-webhook"):
        # charge.refunded webhook. We do process this but currently we don't use it for anything.
        stripe_charge_refunded(
            "charge.refunded", load_webhook_fixture("charge.refunded")
        )

    # Payment should be marked as fully refunded.
    assert payment.state == "refunded"
    assert all(
        purchase.state == "refunded" for purchase in payment.purchases
    ), "Purchases should be marked as refunded after refund"
