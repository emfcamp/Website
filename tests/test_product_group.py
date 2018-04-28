from decimal import Decimal
from datetime import datetime
import pytest
import random
import string
import unittest
from unittest.mock import patch, Mock

from .core import get_app
from models.basket import Basket
from models.exc import CapacityException
from models.payment import BankPayment
from models.product import (
    Product, ProductGroup, PriceTier, Price
)
from models.purchase import (
    PurchaseStateException, PurchaseTransferException,
    PURCHASE_STATES,
)
from models.user import User


def random_string(length):
    return ''.join(random.choice(string.ascii_lowercase + string.digits)
                   for _ in range(length))

class SingleProductGroupTest(unittest.TestCase):
    item_template = 'killer_tent{}'

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

    def create_fixtures(self):
        self.item_name = self.item_template.format(random_string(8))
        self.item = ProductGroup(type='tent', name=self.item_name, capacity_max=1, expires=datetime(2012, 8, 31))
        self.db.session.add(self.item)

        self.db.session.commit()

    def create_purchases(self, tier, count):
        basket = Basket(self.user, 'GBP')
        basket[tier] = count
        basket.create_purchases()
        basket.ensure_purchase_capacity()
        payment = basket.create_payment(BankPayment)
        assert len(payment.purchases) == count
        self.db.session.commit()

        return payment.purchases

    def test_has_capacity(self):
        with self.app.app_context():
            self.create_fixtures()

            # With no parent this is a trivial test
            self.assertTrue(self.item.has_capacity())

            with self.assertRaises(ValueError):
                self.item.has_capacity(-1)

    @unittest.skip('not how it works any more')
    def test_has_expired(self):
        with self.app.app_context():
            self.create_fixtures()

            with patch('models.mixins.datetime') as mock_good_datetime:
                mock_good_datetime.utcnow = Mock(return_value=datetime(2012, 8, 2))
                self.assertFalse(self.item.has_expired())

            with patch('models.mixins.datetime') as mock_expired_datetime:
                mock_expired_datetime.utcnow = Mock(return_value=datetime(2012, 9, 2))
                self.assertTrue(self.item.has_expired())

    @unittest.skip('not how it works any more')
    def test_reserve_tickets(self):
        with self.app.app_context():
            self.create_fixtures()

            # Will raise an error if we try to issue once expired
            with patch('models.mixins.datetime') as mock_expired_datetime:
                mock_expired_datetime.utcnow = Mock(return_value=datetime(2012, 9, 2))

                with self.assertRaises(CapacityException):
                    self.create_purchases(item, 1)

            # Now test with a good value for now()
            with patch('models.mixins.datetime') as mock_good_datetime:
                mock_good_datetime.utcnow = Mock(return_value=datetime(2012, 8, 2))

                self.create_purchases(item, 1)
                self.db.session.commit()

                self.assertFalse(self.item.has_capacity())
                with self.assertRaises(CapacityException):
                    self.create_purchases(item, 1)

    def test_capacity_remaining(self):
        with self.app.app_context():
            self.create_fixtures()

            self.assertEqual(self.item.capacity_max, self.item.get_total_remaining_capacity())

            self.item.capacity_used = self.item.capacity_max

            self.db.session.commit()
            self.assertEqual(0, self.item.get_total_remaining_capacity())


class ProductGroupInitialiseTest(unittest.TestCase):
    parent_group_template = 'parent_group{}'
    group_template = 'group{}'

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

    def create_fixtures(self):
        self.parent_group_name = self.parent_group_template.format(random_string(8))
        self.parent_group = ProductGroup(type='test', name=self.parent_group_name, capacity_max=10)
        self.db.session.add(self.parent_group)

        self.db.session.commit()

    def test_capacity_propagation(self):
        with self.app.app_context():
            self.create_fixtures()

            self.group_name = self.group_template.format(random_string(8))
            # Create a product group without a parent so validate_capacity_max returns early
            self.group = ProductGroup(type='test')
            assert self.group.name is None
            assert self.group.id is None

            # Now add a parent
            self.group.parent = self.parent_group

            # This should call validate_capacity_max, which may flush the session, which we don't want
            self.group.capacity_max = 5
            assert self.group.id is not None


class MultipleProductGroupTest(unittest.TestCase):
    user_email_template = '{}@test.invalid'
    group_template = 'group{}'
    product1_name = 'product'
    product2_name = 'product2'
    tier1_1_name = 'tier1'
    tier1_2_name = 'tier2'
    tier3_name = 'tier3'

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

    def create_fixtures(self):
        self.user_email = self.user_email_template.format(random_string(8))
        self.user = User(self.user_email, 'test_user')
        self.db.session.add(self.user)

        self.group_name = self.group_template.format(random_string(8))
        self.group = ProductGroup(type='test', name=self.group_name, capacity_max=10)
        self.product1 = Product(name=self.product1_name, parent=self.group, capacity_max=3)
        self.tier1_1 = PriceTier(name=self.tier1_1_name, parent=self.product1)
        self.price1_1 = Price(price_tier=self.tier1_1, currency='GBP', price_int=10)
        self.db.session.add(self.tier1_1)

        self.tier1_2 = PriceTier(name=self.tier1_2_name, parent=self.product1)
        self.price1_2 = Price(price_tier=self.tier1_2, currency='GBP', price_int=20)
        self.db.session.add(self.tier1_2)

        self.product2 = Product(name=self.product2_name, parent=self.group)
        self.tier3 = PriceTier(name=self.tier3_name, parent=self.product2)
        self.price3 = Price(price_tier=self.tier3, currency='GBP', price_int=30)
        self.db.session.add(self.tier3)

        self.db.session.commit()

    def create_purchases(self, tier, count):
        basket = Basket(self.user, 'GBP')
        basket[tier] = count
        basket.create_purchases()
        basket.ensure_purchase_capacity()
        payment = basket.create_payment(BankPayment)
        assert len(payment.purchases) == count
        self.db.session.commit()

        return payment.purchases

    def test_capacity_propagation(self):
        with self.app.app_context():
            self.create_fixtures()

            # Check all our items have the correct initial capacity
            assert self.group.get_total_remaining_capacity() == 10

            assert self.product1.get_total_remaining_capacity() == 3
            assert self.tier1_1.get_total_remaining_capacity() == 3
            assert self.tier1_2.get_total_remaining_capacity() == 3

            assert self.product2.get_total_remaining_capacity() == 10
            assert self.tier3.get_total_remaining_capacity() == 10

            # Issue three instances to exhaust product1
            self.create_purchases(self.tier1_1, 3)
            self.db.session.commit()

            # Now we shouldn't be able to issue any more tickets from this product
            with pytest.raises(CapacityException):
                self.create_purchases(self.tier1_1, 1)

            with pytest.raises(CapacityException):
                self.create_purchases(self.tier1_2, 1)

            # All the capacity went from product1
            assert self.tier1_1.get_total_remaining_capacity() == 0
            assert self.tier1_2.get_total_remaining_capacity() == 0
            assert self.product1.get_total_remaining_capacity() == 0

            # product2 still has capacity but is limited by the parent
            assert self.group.get_total_remaining_capacity() == 7
            assert self.product2.get_total_remaining_capacity() == 7
            assert self.tier3.get_total_remaining_capacity() == 7

    def test_get_cheapest(self):
        with self.app.app_context():
            self.create_fixtures()

            price1 = Price(price_tier=self.tier1_1, currency='GBP', price_int=5)
            price2 = Price(price_tier=self.tier1_2, currency='GBP', price_int=500)

            self.db.session.add(price1)
            self.db.session.add(price2)
            self.db.session.commit()

            assert price1 == self.product1.get_cheapest_price('GBP')


class PurchaseTest(unittest.TestCase):
    user_email_template = '{}@test.invalid'
    group_template = 'pg{}'
    product_name = 'product'
    tier_name = 'tier'

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

    def create_fixtures(self):
        self.user_email = self.user_email_template.format(random_string(8))
        self.user = User(self.user_email, 'test_user')
        self.db.session.add(self.user)

        self.group_name = self.group_template.format(random_string(8))
        self.group = ProductGroup(type='admissions', name=self.group_name)
        self.product = Product(name=self.product_name, capacity_max=3, parent=self.group)
        self.tier = PriceTier(name=self.tier_name, parent=self.product)
        self.price = Price(price_tier=self.tier, currency='GBP', price_int=666)
        # These have `cascade=all` so just add the bottom of the hierarchy
        self.db.session.add(self.price)

        self.db.session.commit()

    def create_purchases(self, tier, count):
        basket = Basket(self.user, 'GBP')
        basket[tier] = count
        basket.create_purchases()
        basket.ensure_purchase_capacity()
        payment = basket.create_payment(BankPayment)
        assert len(payment.purchases) == count
        self.db.session.commit()

        return payment.purchases

    def test_create_purchases(self):
        with self.app.app_context():
            self.create_fixtures()

            assert self.tier.capacity_used == 0

            purchases = self.create_purchases(self.tier, 1)
            purchase = purchases[0]

            assert self.tier.capacity_used == 1
            assert self.product.capacity_used == 1

            # NB: Decimal('6.66') != Decimal(6.66) == Decimal(float(6.66)) ~= 6.6600000000000001
            assert purchase.price.value == Decimal('6.66')

            # Test issuing multiple instances works
            new_purchases = self.create_purchases(self.tier, 2)
            assert len(new_purchases) == 2
            assert self.product.capacity_used == 3

            # Test issuing beyond capacity errors
            with pytest.raises(CapacityException):
                self.create_purchases(self.tier, 1)

    def test_purchase_state_machine(self):
        states_dict = PURCHASE_STATES

        # 'reserved' is the start state, all other states must
        # exist as the next_state of some state.
        # e.g. "payment-pending" and "paid" are next states for
        # "reserved" and "payment-pending" respectively.
        self.assertIn('reserved', states_dict)
        seen_in_next_states = list(states_dict.keys())
        seen_in_next_states.remove('reserved')

        for state in states_dict:
            next_states = states_dict[state]

            for allowed_state in next_states:
                self.assertIn(allowed_state, states_dict)
                if allowed_state in seen_in_next_states:
                    seen_in_next_states.remove(allowed_state)

        self.assertEqual(0, len(seen_in_next_states), 'Found unreachable states: %s' % seen_in_next_states)

    def test_set_state(self):
        with self.app.app_context():
            self.create_fixtures()

            purchases = self.create_purchases(self.tier, 1)
            purchase = purchases[0]

            with self.assertRaises(PurchaseStateException):
                purchase.set_state('disallowed-state')

            with self.assertRaises(PurchaseStateException):
                purchase.set_state('receipt-emailed')

            purchase.set_state('payment-pending')

            self.assertEqual('payment-pending', purchase.state)

    def test_product_group_get_counts_by_state(self):
        with self.app.app_context():
            self.create_fixtures()

            # Test it works at the PriceTier level
            purchases = self.create_purchases(self.tier, 1)
            purchase1 = purchases[0]

            expected = {
                'reserved': 1,
            }

            assert self.tier.purchase_count_by_state == expected
            assert self.product.purchase_count_by_state == expected
            assert self.group.purchase_count_by_state == expected

            # Test that other states show up
            purchase1.set_state('payment-pending')
            self.db.session.commit()

            expected = {
                'payment-pending': 1,
            }

            assert self.tier.purchase_count_by_state == expected
            assert self.product.purchase_count_by_state == expected
            assert self.group.purchase_count_by_state == expected

            # Add another purchase in another tier
            self.tier2 = PriceTier(name='2', parent=self.product)
            self.price = Price(price_tier=self.tier2, currency='GBP', price_int=666)
            self.db.session.commit()
            self.create_purchases(self.tier2, 1)

            assert self.tier.purchase_count_by_state == expected

            expected = {
                'payment-pending': 1,
                'reserved': 1,
            }

            assert self.product.purchase_count_by_state == expected
            assert self.group.purchase_count_by_state == expected

    @unittest.skip('This appears to be a test for an otherwise unused function')
    def test_get_purchase_count(self):
        with self.app.app_context():
            self.create_fixtures()

            # Test it works at the PriceTier level
            purchases = self.create_purchases(self.tier, 1)
            purchase = purchases[0]
            purchase.state = 'paid'
            self.db.session.commit()
            assert self.tier.get_purchase_count() == 1

            assert self.group.get_purchase_count() == 1

    def test_check_in(self):
        with self.app.app_context():
            self.create_fixtures()

            purchases = self.create_purchases(self.tier, 1)
            purchase = purchases[0]

            purchase.state = 'receipt-emailed'
            assert purchase.checked_in is False
            purchase.check_in()
            assert purchase.checked_in is True


class ProductTransferTest(unittest.TestCase):
    group_template = 'pg{}'
    product_name = 'product'
    tier_name = 'tier'
    user1_email_template = 'a-{}@test.invalid'
    user2_email_template = 'b-{}@test.invalid'

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

    def create_fixtures(self):
        self.user1_email = self.user1_email_template.format(random_string(8))
        self.user2_email = self.user2_email_template.format(random_string(8))
        self.user1 = User(self.user1_email, 'test_user1')
        self.user2 = User(self.user2_email, 'test_user2')
        self.db.session.add(self.user1)
        self.db.session.add(self.user2)

        self.group_name = self.group_template.format(random_string(8))
        self.group = ProductGroup(type='admissions', name=self.group_name)
        self.product = Product(name=self.product_name, parent=self.group)
        self.tier = PriceTier(name=self.tier_name, parent=self.product)
        self.price = Price(price_tier=self.tier, currency='GBP', price_int=666)

        self.db.session.add(self.price)
        self.db.session.commit()

        # PriceTier needs to have been committed before this
        basket = Basket(self.user1, 'GBP')
        basket[self.tier] = 1
        basket.create_purchases()
        basket.ensure_purchase_capacity()
        payment = basket.create_payment(BankPayment)
        assert len(payment.purchases) == 1
        self.db.session.commit()

    def test_transfer(self):
        with self.app.app_context():
            self.create_fixtures()

            item = self.user1.purchased_products[0]

            item.price_tier.allow_check_in = True
            item.price_tier.is_transferable = False

            with self.assertRaises(PurchaseTransferException) as e:
                item.transfer(self.user1, self.user2)
                self.assertIn('Only paid items may be transferred.', e.args[0])

            item.state = 'paid'
            self.db.session.commit()

            with self.assertRaises(PurchaseTransferException) as e:
                item.transfer(self.user1, self.user2)
                self.assertIn('not transferable', e.args[0])

            with self.assertRaises(PurchaseTransferException) as e:
                item.transfer(self.user2, self.user1)

                self.assertIn('does not own this item', e.args[0])

            self.db.session.commit()
            item.price_tier.parent.set_attribute('is_transferable', True)

            with self.assertRaises(PurchaseTransferException) as e:
                item.transfer(self.user1, self.user1)

                self.assertIn('users must be different', e.args[0])

            item.transfer(self.user1, self.user2)
            self.db.session.commit()

            self.assertEqual(item.owner_id, self.user2.id)
            self.assertEqual(item.purchaser_id, self.user1.id)

            self.assertEqual(item, self.user2.get_tickets()[0])
            self.assertNotIn(item, self.user1.get_tickets())

            xfer = item.transfers[0]

            self.assertEqual(xfer.to_user.id, self.user2.id)
            self.assertEqual(xfer.from_user.id, self.user1.id)


