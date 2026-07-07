from datetime import datetime, timedelta

import pytest
from freezegun import freeze_time

from apps.config import config
from main import db
from models.basket import Basket
from models.payment import BankPayment
from models.product import Price, PriceTier, Product, ProductGroup
from models.volunteer import buildup
from models.volunteer.buildup import BuildupVolunteer


@pytest.fixture
def admission_tier(db):
    group = ProductGroup(type="admissions", name="test-admissions-group")
    db.session.add(group)
    product = Product(name="test-admission-product", parent=group)
    tier = PriceTier(name="test-admission-tier", parent=product)
    price = Price(price_tier=tier, currency="GBP", price_int=100)
    db.session.add(price)
    db.session.flush()
    return tier


def buy_admission_ticket(tier, user, *, redeem):
    basket = Basket(user, "GBP", None)
    basket[tier] = 1
    basket.create_purchases()
    basket.ensure_purchase_capacity()
    payment = basket.create_payment(BankPayment)
    db.session.add(payment)
    db.session.flush()

    purchase = payment.purchases[0]
    purchase.state = "paid"
    if redeem:
        purchase.product.set_attribute("is_redeemable", True)
        purchase.redeem()
    db.session.flush()
    return purchase


def test_permitted_shift_times_default(volunteer):
    assert volunteer.permitted_shift_times == (config.event_start, config.event_end)


def test_permitted_shift_times_buildup(db, user, volunteer):
    db.session.add(
        BuildupVolunteer(user_id=user.id, arrival_date=datetime.now(), departure_date=datetime.now())
    )
    db.session.flush()

    assert volunteer.permitted_shift_times == (buildup.buildup_start(), buildup.teardown_end())


def test_permitted_shift_times_checked_in(admission_tier, user, volunteer):
    buy_admission_ticket(admission_tier, user, redeem=True)

    assert volunteer.permitted_shift_times == (
        config.event_start - timedelta(days=1),
        config.event_end,
    )


def test_permitted_shift_times_not_checked_in(admission_tier, user, volunteer):
    buy_admission_ticket(admission_tier, user, redeem=False)

    assert volunteer.permitted_shift_times == (config.event_start, config.event_end)


def test_permitted_shift_times_buildup_and_checked_in(db, admission_tier, user, volunteer):
    db.session.add(
        BuildupVolunteer(user_id=user.id, arrival_date=datetime.now(), departure_date=datetime.now())
    )
    db.session.flush()
    buy_admission_ticket(admission_tier, user, redeem=True)

    assert volunteer.permitted_shift_times == (buildup.buildup_start(), buildup.teardown_end())


def test_permitted_shift_times_checked_in_after_event_start(admission_tier, user, volunteer):
    buy_admission_ticket(admission_tier, user, redeem=True)

    with freeze_time(config.event_start + timedelta(hours=1)):
        assert volunteer.permitted_shift_times == (config.event_start, config.event_end)
