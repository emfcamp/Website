import unittest
import pytest

from decimal import Decimal
from datetime import datetime
from unittest.mock import patch, Mock

from .core import get_app
from models.user import User
from models.product import (
    Product, ProductGroup, PriceTier, Price
)
from models.exc import CapacityException
from models.purchase import PurchaseStateException, PurchaseTransferException, PURCHASE_STATES
from models import Purchase


class SingleProductGroupTest(unittest.TestCase):
    item_name = 'killer_tent'

    def get_item(self):
        return ProductGroup.get_by_name(self.item_name)

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

        with self.app.app_context():
            item = ProductGroup(name=self.item_name, capacity_max=1, expires=datetime(2012, 8, 31))
            self.db.session.add(item)

            self.db.session.commit()

    def test_has_capacity(self):
        with self.app.app_context():
            # With no parent this is a trivial test
            item = self.get_item()
            self.assertTrue(item.has_capacity())

            with self.assertRaises(ValueError):
                item.has_capacity(-1)

    def test_has_expired(self):
        with self.app.app_context():
            item = self.get_item()

            with patch('models.mixins.datetime') as mock_good_datetime:
                mock_good_datetime.utcnow = Mock(return_value=datetime(2012, 8, 2))
                self.assertFalse(item.has_expired())

            with patch('models.mixins.datetime') as mock_expired_datetime:
                mock_expired_datetime.utcnow = Mock(return_value=datetime(2012, 9, 2))
                self.assertTrue(item.has_expired())

    def test_issue_instance(self):
        with self.app.app_context():
            item = self.get_item()

            # Will raise an error if we try to issue once expired
            with patch('models.mixins.datetime') as mock_expired_datetime:
                mock_expired_datetime.utcnow = Mock(return_value=datetime(2012, 9, 2))

                with self.assertRaises(CapacityException):
                    item.issue_instances(self.db.session)

            # Now test with a good value for now()
            with patch('models.mixins.datetime') as mock_good_datetime:
                mock_good_datetime.utcnow = Mock(return_value=datetime(2012, 8, 2))

                item.issue_instances(self.db.session)
                self.db.session.commit()

                self.assertFalse(item.has_capacity())
                with self.assertRaises(CapacityException):
                    item.issue_instances(self.db.session)

    def test_capacity_remaining(self):
        with self.app.app_context():
            item = self.get_item()
            self.assertEqual(item.capacity_max, item.get_total_remaining_capacity())

            item.capacity_used = item.capacity_max

            self.db.session.commit()
            self.assertEqual(0, item.get_total_remaining_capacity())


class MultipleProductGroupTest(unittest.TestCase):
    def get_item(self, name):
        return ProductGroup.get_by_name(name)

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

    def create_products(self):
        self.parent = ProductGroup(name='parent', capacity_max=10)
        self.product1 = Product(name='product', parent=self.parent, capacity_max=3)
        self.tier1_1 = PriceTier(name='tier1', parent=self.product1)
        self.db.session.add(self.tier1_1)

        self.tier1_2 = PriceTier(name='tier2', parent=self.product1)
        self.db.session.add(self.tier1_2)

        self.product2 = Product(name='product2', parent=self.parent)
        self.tier2_1 = PriceTier(name='tier2_1', parent=self.product2)
        self.db.session.add(self.tier2_1)

        self.db.session.commit()

    def test_capacity_propagation(self):
        with self.app.app_context():
            self.create_products()

            # Check all our items have the correct initial capacity
            assert self.parent.get_total_remaining_capacity() == 10

            assert self.product1.get_total_remaining_capacity() == 3
            assert self.tier1_1.get_total_remaining_capacity() == 3
            assert self.tier1_2.get_total_remaining_capacity() == 3

            assert self.product2.get_total_remaining_capacity() == 10
            assert self.tier2_1.get_total_remaining_capacity() == 10

            # Issue three instances to exhaust product1
            self.tier1_1.issue_instances(self.db.session, 3)
            self.db.session.commit()

            # Now we shouldn't be able to issue any more tickets from this product
            with pytest.raises(CapacityException):
                self.tier1_1.issue_instances(self.db.session, 1)

            with pytest.raises(CapacityException):
                self.tier1_2.issue_instances(self.db.session, 1)

            # All the capacity went from product1
            assert self.tier1_1.get_total_remaining_capacity() == 0
            assert self.tier1_2.get_total_remaining_capacity() == 0
            assert self.product1.get_total_remaining_capacity() == 0

            # product2 still has capacity but is limited by the parent
            assert self.parent.get_total_remaining_capacity() == 7
            assert self.product2.get_total_remaining_capacity() == 7
            assert self.tier2_1.get_total_remaining_capacity() == 7

    def test_get_cheapest(self):
        with self.app.app_context():
            self.create_products()

            price1 = Price(price_tier=self.tier1_1, currency='gbp', price_int=5)
            price2 = Price(price_tier=self.tier1_2, currency='gbp', price_int=500)

            self.db.session.add(price1)
            self.db.session.add(price2)
            self.db.session.commit()

            assert price1 == self.product1.get_lowest_price_tier().get_price_object('gbp')


class PurchaseTest(unittest.TestCase):
    pg_name = 'pg'
    product_name = 'product'
    tier_name = 'tier'
    user_email = 'a@b.c'

    def get_purchase(self, session, tier=None):
        user = User.get_by_email(self.user_email)
        if tier is None:
            tier = PriceTier.get_by_name(self.tier_name)
            assert tier is not None

        instance = Purchase.create_instances(session, user, tier, 'gbp')[0]

        session.add(instance)
        session.commit()

        return instance

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

        with self.app.app_context():

            user = User(self.user_email, 'test_user')
            self.db.session.add(user)

            group = ProductGroup(name=self.pg_name, type="admission_ticket")
            product = Product(name=self.product_name, capacity_max=3, parent=group)
            tier = PriceTier(name=self.tier_name, parent=product)
            price = Price(price_tier=tier, currency="gbp", price_int=666)
            # These have `cascade=all` so just add the bottom of the hierarchy
            self.db.session.add(price)

            self.db.session.commit()

    def test_create_instances(self):
        with self.app.app_context():
            user = User.get_by_email(self.user_email)
            tier = PriceTier.get_by_name(self.tier_name)
            product = Product.get_by_name(self.product_name)
            assert tier.capacity_used == 0

            instance = self.get_purchase(self.db.session)

            assert tier.capacity_used == 1
            assert product.capacity_used == 1

            # NB: Decimal('6.66') != Decimal(6.66) == Decimal(float(6.66)) ~= 6.6600000000000001
            assert instance.price.value == Decimal('6.66')

            # Test issuing multiple instances works
            more_instances = Purchase.create_instances(self.db.session, user, tier, 'gbp', 2)
            assert len(more_instances) == 2
            assert product.capacity_used == 3

            # Test issuing beyond capacity errors
            with pytest.raises(CapacityException):
                Purchase.create_instances(self.db.session, user, tier, 'gbp')

    def test_product_instance_state_machine(self):
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
            instance = self.get_purchase(self.db.session)

            with self.assertRaises(PurchaseStateException):
                instance.set_state('disallowed-state')

            with self.assertRaises(PurchaseStateException):
                instance.set_state('receipt-emailed')

            instance.set_state('payment-pending')

            self.assertEqual('payment-pending', instance.state)

    def test_product_group_get_counts_by_state(self):
        with self.app.app_context():
            # Test it works at the PriceTier level
            tier1 = PriceTier.get_by_name(self.tier_name)
            instance1 = self.get_purchase(self.db.session)

            states_count = tier1.get_purchase_count_by_state()
            expect = {s: 0 for s in PURCHASE_STATES.keys()}
            expect['reserved'] = 1

            assert expect == states_count

            # Now test we see the same in a ProductGroup
            product = Product.get_by_name(self.product_name)

            product_states = product.get_purchase_count_by_state()

            assert expect == product_states

            # Test that other states show up
            instance1.set_state('payment-pending')
            self.db.session.add(instance1)
            self.db.session.commit()

            product_states = product.get_purchase_count_by_state()
            expect['reserved'] = 0
            expect['payment-pending'] = 1

            assert expect == product_states

            # Add another instance in another tier
            tier2 = PriceTier(name='2', parent=product)
            price = Price(price_tier=tier2, currency="gbp", price_int=666)
            self.db.session.add(price)
            self.get_purchase(self.db.session, tier2)

            product_states = product.get_purchase_count_by_state()
            expect['reserved'] = 1

            assert expect == product_states

    def test_get_purchase_count(self):
        with self.app.app_context():
            # Test it works at the PriceTier level
            tier = PriceTier.get_by_name(self.tier_name)
            instance = self.get_purchase(self.db.session)
            instance.state = 'paid'
            self.db.session.commit()
            assert tier.get_purchase_count() == 1

            parent = ProductGroup.get_by_name(self.pg_name)
            assert parent.get_purchase_count() == 1

    def test_user_limit(self):
        with self.app.app_context():
            user = User.get_by_email(self.user_email)
            tier = PriceTier.get_by_name(self.tier_name)
            tier.personal_limit = 1

            self.db.session.commit()

            self.assertEqual(1, tier.user_limit(user))

            self.get_purchase(self.db.session)

            self.assertEqual(0, tier.user_limit(user))
            self.assertTrue(tier.has_capacity())

    def test_check_in(self):
        with self.app.app_context():
            ticket = self.get_purchase(self.db.session)

            ticket.state = 'receipt-emailed'
            assert ticket.checked_in is False
            ticket.check_in()
            assert ticket.checked_in is True


class ProductTransferTest(unittest.TestCase):
    pg_name = 'pg'
    user1_email = 'a@b.c'
    user2_email = 'b@b.c'

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

        with self.app.app_context():

            user1 = User(self.user1_email, 'test_user1')
            user2 = User(self.user2_email, 'test_user2')
            self.db.session.add(user1)
            self.db.session.add(user2)

            product_group = ProductGroup(name="product_group", type="admission_ticket")
            product = Product(name="product", parent=product_group)
            tier = PriceTier(name=self.pg_name, parent=product)
            price = Price(price_tier=tier, currency="gbp", price_int=666)
            # These have `cascade=all` so just add the bottom of the hierarchy
            self.db.session.add(price)
            self.db.session.commit()

            # PriceTier needs to have been committed before this
            instance = Purchase.create_instances(self.db.session, user1, tier, 'gbp')[0]
            self.db.session.add(instance)

            self.db.session.commit()

    def test_transfer(self):
        with self.app.app_context():
            user1 = User.get_by_email(self.user1_email)
            user2 = User.get_by_email(self.user2_email)
            item = user1.purchased_products[0]

            item.price_tier.allow_check_in = True
            item.price_tier.is_transferable = False

            with self.assertRaises(PurchaseTransferException) as e:
                item.transfer(user1, user2, self.db.session)
                self.assertIn('Only paid items may be transferred.', e.args[0])

            item.state = 'paid'
            self.db.session.commit()

            with self.assertRaises(PurchaseTransferException) as e:
                item.transfer(user1, user2, self.db.session)
                self.assertIn('not transferable', e.args[0])

            with self.assertRaises(PurchaseTransferException) as e:
                item.transfer(user2, user1, self.db.session)

                self.assertIn('does not own this item', e.args[0])

            self.db.session.commit()
            item.price_tier.parent.set_attribute('is_transferable', True)

            with self.assertRaises(PurchaseTransferException) as e:
                item.transfer(user1, user1, self.db.session)

                self.assertIn('users must be different', e.args[0])

            item.transfer(user1, user2, self.db.session)
            self.db.session.commit()

            self.assertEqual(item.owner_id, user2.id)
            self.assertEqual(item.purchaser_id, user1.id)

            self.assertEqual(item, user2.get_tickets()[0])
            self.assertNotIn(item, user1.get_tickets())

            xfer = item.transfers[0]

            self.assertEqual(xfer.to_user.id, user2.id)
            self.assertEqual(xfer.from_user.id, user1.id)
