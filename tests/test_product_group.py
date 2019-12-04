from decimal import Decimal
from datetime import datetime
import pytest
import random
import string

from models.basket import Basket
from models.exc import CapacityException
from models.payment import BankPayment
from models.product import Product, ProductGroup, PriceTier, Price
from models.purchase import (
    PurchaseStateException,
    PurchaseTransferException,
    PURCHASE_STATES,
    CheckinStateException,
)
from models.user import User
from main import db


@pytest.fixture()
def tent(db):
    item_template = "killer_tent{}"
    item_name = item_template.format(random_string(8))
    item = ProductGroup(
        type="tent", name=item_name, capacity_max=1, expires=datetime(2012, 8, 31)
    )
    db.session.add(item)
    db.session.commit()
    yield item
    db.session.delete(item)
    db.session.commit()


@pytest.fixture()
def parent_group(db):
    parent_group_template = "parent_group{}"
    group_name = parent_group_template.format(random_string(8))
    group = ProductGroup(type="admissions", name=group_name, capacity_max=10)
    db.session.add(group)
    db.session.commit()
    yield group
    # db.session.delete(group)
    # db.session.commit()


def create_purchases(tier, count, user):
    basket = Basket(user, "GBP", None)
    basket[tier] = count
    basket.create_purchases()
    basket.ensure_purchase_capacity()
    payment = basket.create_payment(BankPayment)

    db.session.add(payment)
    db.session.commit()
    assert len(payment.purchases) == count
    return payment.purchases


def random_string(length):
    return "".join(
        random.choice(string.ascii_lowercase + string.digits) for _ in range(length)
    )


def test_has_capacity(tent):
    # With no parent this is a trivial test
    assert tent.has_capacity()

    with pytest.raises(ValueError):
        tent.has_capacity(-1)


def test_capacity_remaining(tent, db):
    assert tent.capacity_max == tent.get_total_remaining_capacity()

    tent.capacity_used = tent.capacity_max

    db.session.commit()
    assert tent.get_total_remaining_capacity() == 0


def test_validate_capacity_max(db, parent_group):
    group_template = "group{}"
    group_name = group_template.format(random_string(8))
    # Create a product group without a parent so validate_capacity_max returns early
    group = ProductGroup(type="test")
    assert group.name is None
    assert group.id is None

    # Now add a parent
    group.parent = parent_group

    # This should call validate_capacity_max, which may flush the session, which we don't want
    group.capacity_max = 5

    # If that was OK, we can continue
    group.name = group_name
    db.session.flush()
    assert group.id is not None


def test_capacity_propagation(db, parent_group, user):
    product1 = Product(name="product", parent=parent_group, capacity_max=3)
    tier1_1 = PriceTier(name="tier1", parent=product1)
    Price(price_tier=tier1_1, currency="GBP", price_int=10)
    db.session.add(tier1_1)

    tier1_2 = PriceTier(name="tier2", parent=product1)
    Price(price_tier=tier1_2, currency="GBP", price_int=20)
    db.session.add(tier1_2)

    product2 = Product(name="product2", parent=parent_group)
    tier3 = PriceTier(name="tier3", parent=product2)
    Price(price_tier=tier3, currency="GBP", price_int=30)
    db.session.commit()

    # Check all our items have the correct initial capacity
    assert parent_group.get_total_remaining_capacity() == 10

    assert product1.get_total_remaining_capacity() == 3
    assert tier1_1.get_total_remaining_capacity() == 3
    assert tier1_2.get_total_remaining_capacity() == 3

    assert product2.get_total_remaining_capacity() == 10
    assert tier3.get_total_remaining_capacity() == 10

    # Issue three instances to exhaust product1
    create_purchases(tier1_1, 3, user)
    db.session.commit()

    # Now we shouldn't be able to issue any more tickets from this product
    with pytest.raises(CapacityException):
        create_purchases(tier1_1, 1, user)

    with pytest.raises(CapacityException):
        create_purchases(tier1_2, 1, user)

    db.session.commit()
    # All the capacity went from product1
    assert tier1_1.get_total_remaining_capacity() == 0
    assert tier1_2.get_total_remaining_capacity() == 0
    assert product1.get_total_remaining_capacity() == 0

    # produtill has capacity but is limited by the parent
    assert parent_group.get_total_remaining_capacity() == 7
    assert product2.get_total_remaining_capacity() == 7
    assert tier3.get_total_remaining_capacity() == 7

    price1 = Price(price_tier=tier1_1, currency="GBP", price_int=5)
    price2 = Price(price_tier=tier1_2, currency="GBP", price_int=500)

    db.session.add(price1)
    db.session.add(price2)
    db.session.commit()

    assert price1 == product1.get_cheapest_price("GBP")


def test_create_purchases(db, parent_group, user):
    product = Product(name="product", capacity_max=3, parent=parent_group)
    tier = PriceTier(name="tier", parent=product)
    price = Price(price_tier=tier, currency="GBP", price_int=666)
    db.session.add(price)
    db.session.commit()

    assert tier.capacity_used == 0

    purchases = create_purchases(tier, 1, user)
    purchase = purchases[0]

    assert tier.capacity_used == 1
    assert product.capacity_used == 1

    # NB: Decimal('6.66') != Decimal(6.66) == Decimal(float(6.66)) ~= 6.6600000000000001
    assert purchase.price.value == Decimal("6.66")

    # Test issuing multiple instances works
    new_purchases = create_purchases(tier, 2, user)
    assert len(new_purchases) == 2
    assert product.capacity_used == 3

    # Test issuing beyond capacity errors
    with pytest.raises(CapacityException):
        create_purchases(tier, 1, user)


def test_purchase_state_machine():
    states_dict = PURCHASE_STATES

    # 'reserved' is the start state, all other states must
    # exist as the next_state of some state.
    # e.g. "payment-pending" and "paid" are next states for
    # "reserved" and "payment-pending" respectively.
    assert "reserved" in states_dict
    seen_in_next_states = list(states_dict.keys())
    seen_in_next_states.remove("reserved")

    for state in states_dict:
        next_states = states_dict[state]

        for allowed_state in next_states:
            assert allowed_state in states_dict
            if allowed_state in seen_in_next_states:
                seen_in_next_states.remove(allowed_state)

    assert len(seen_in_next_states) == 0


def test_set_state(db, parent_group, user):
    product = Product(name="product", capacity_max=3, parent=parent_group)
    tier = PriceTier(name="tier", parent=product)
    price = Price(price_tier=tier, currency="GBP", price_int=666)
    db.session.add(price)
    db.session.commit()

    purchases = create_purchases(tier, 1, user)
    purchase = purchases[0]

    with pytest.raises(PurchaseStateException):
        purchase.set_state("disallowed-state")

    purchase.set_state("payment-pending")

    assert purchase.state == "payment-pending", purchase.state


def test_product_group_get_counts_by_state(db, parent_group, user):
    product = Product(name="product", capacity_max=3, parent=parent_group)
    tier = PriceTier(name="tier", parent=product)
    price = Price(price_tier=tier, currency="GBP", price_int=666)
    db.session.add(price)
    db.session.commit()

    # Test it works at the PriceTier level
    purchases = create_purchases(tier, 1, user)
    purchase1 = purchases[0]

    expected = {"reserved": 1}

    assert tier.purchase_count_by_state == expected
    assert product.purchase_count_by_state == expected
    assert parent_group.purchase_count_by_state == expected

    # Test that other states show up
    purchase1.set_state("payment-pending")
    db.session.commit()

    expected = {"payment-pending": 1}

    assert tier.purchase_count_by_state == expected
    assert product.purchase_count_by_state == expected
    assert parent_group.purchase_count_by_state == expected

    # Add another purchase in another tier
    tier2 = PriceTier(name="2", parent=product)
    price = Price(price_tier=tier2, currency="GBP", price_int=666)
    db.session.commit()
    create_purchases(tier2, 1, user)

    assert tier.purchase_count_by_state == expected

    expected = {"payment-pending": 1, "reserved": 1}

    assert product.purchase_count_by_state == expected
    assert parent_group.purchase_count_by_state == expected


def test_check_in(db, parent_group, user):
    product = Product(name="product", capacity_max=3, parent=parent_group)
    tier = PriceTier(name="tier", parent=product)
    price = Price(price_tier=tier, currency="GBP", price_int=666)
    db.session.add(price)
    db.session.commit()

    purchases = create_purchases(tier, 1, user)
    purchase = purchases[0]

    with pytest.raises(PurchaseStateException):
        # Issuing tickets should fail if the purchase hasn't been paid for
        purchase.ticket_issued = True

    with pytest.raises(CheckinStateException):
        # Likewise, checking in should fail.
        purchase.check_in()

    purchase.state = "paid"
    db.session.commit()

    purchase.ticket_issued = True
    assert purchase.checked_in is False
    purchase.check_in()
    assert purchase.checked_in is True


def test_transfer(db, user, parent_group):
    user1 = user
    user2 = User("test_user_{}@test.invalid".format(random_string(8)), "test_user2")
    db.session.add(user2)

    product = Product(name="product", parent=parent_group)
    tier = PriceTier(name="tier", parent=product)
    price = Price(price_tier=tier, currency="GBP", price_int=666)
    db.session.add(price)
    db.session.commit()

    create_purchases(tier, 1, user1)

    item = user1.purchases[0]

    item.price_tier.allow_check_in = True
    item.price_tier.is_transferable = False

    with pytest.raises(PurchaseTransferException) as e:
        item.transfer(user1, user2)
        assert "Only paid items may be transferred." in e.args[0]

    item.state = "paid"
    db.session.commit()

    with pytest.raises(PurchaseTransferException) as e:
        item.transfer(user1, user2)
        assert "not transferable" in e.args[0]

    with pytest.raises(PurchaseTransferException) as e:
        item.transfer(user2, user1)
        assert "does not own this item" in e.args[0]

    db.session.commit()
    item.price_tier.parent.set_attribute("is_transferable", True)

    with pytest.raises(PurchaseTransferException) as e:
        item.transfer(user1, user1)
        assert "users must be different" in e.args[0]

    item.transfer(user1, user2)
    db.session.commit()

    assert item.owner_id == user2.id
    assert item.purchaser_id == user1.id

    assert item == user2.owned_purchases[0]
    assert item not in user1.owned_purchases

    xfer = item.transfers[0]

    assert xfer.to_user.id == user2.id
    assert xfer.from_user.id == user1.id
