# coding=utf-8
import sys
import unittest

from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import patch, Mock

from .core import get_app
from models.user import User
from models.product_group import (
    PRODUCT_INSTANCE_STATES, ProductGroupException, ProductInstanceStateException,
    ProductTransferException, ProductGroup, PriceTier, Price, ProductInstance, bought_states
)

class SingleProductGroupTest(unittest.TestCase):
    item_name = 'killer_tent'

    def get_item(self):
        return ProductGroup.get_by_name(self.item_name)

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

        with self.app.app_context():
            item = ProductGroup(self.item_name, capacity_max=1, expires=datetime(2012, 8, 31))
            self.db.session.add(item)

            self.db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            self.db.session.delete(self.get_item())
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

            with patch('models.product_group.datetime') as mock_good_datetime:
                mock_good_datetime.utcnow = Mock(return_value=datetime(2012, 8, 2))
                self.assertFalse(item.has_expired())

            with patch('models.product_group.datetime') as mock_expired_datetime:
                mock_expired_datetime.utcnow = Mock(return_value=datetime(2012, 9, 2))
                self.assertTrue(item.has_expired())

    def test_issue_instance(self):
        with self.app.app_context():
            item = self.get_item()

            # Will raise an error if we try to issue once expired
            with patch('models.product_group.datetime') as mock_expired_datetime:
                mock_expired_datetime.utcnow = Mock(return_value=datetime(2012, 9, 2))

                with self.assertRaises(ProductGroupException):
                    item.issue_instances()


            # Now test with a good value for now()
            with patch('models.product_group.datetime') as mock_good_datetime:
                mock_good_datetime.utcnow = Mock(return_value=datetime(2012, 8, 2))

                item.issue_instances()
                self.db.session.commit()

                self.assertFalse(item.has_capacity())
                with self.assertRaises(ProductGroupException):
                    item.issue_instances()

    def test_capacity_remaining(self):
        with self.app.app_context():
            item = self.get_item()
            self.assertEqual(item.capacity_max, item.get_total_remaining_capacity())

            item.capacity_used = item.capacity_max

            self.db.session.commit()
            self.assertEqual(0, item.get_total_remaining_capacity())


class MultipleProductGroupTest(unittest.TestCase):
    parent_name = 'parent'
    group1_name = 'child1'
    group2_name = 'child2'

    def get_item(self, name):
        return ProductGroup.get_by_name(name)

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

        with self.app.app_context(), self.db.session.no_autoflush:

            parent = ProductGroup(self.parent_name, capacity_max=3)
            item1 = PriceTier(self.group1_name, parent=parent)
            self.db.session.add(item1)

            item2 = PriceTier(self.group2_name, parent=parent)
            self.db.session.add(item2)

            self.db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            # deletes should cascade so just delete the parent
            item = self.get_item(name=self.parent_name)
            self.db.session.delete(item)
            self.db.session.commit()

    # We want to mostly check that capacities are inherited & shared
    def test_has_capacity_propagates(self):
        with self.app.app_context():
            item1 = self.get_item(name=self.group1_name)
            item2 = self.get_item(name=self.group2_name)
            parent = self.get_item(name=self.parent_name)

            self.assertEqual(3, item1.get_total_remaining_capacity())
            self.assertEqual(3, item2.get_total_remaining_capacity())
            self.assertEqual(3, parent.get_total_remaining_capacity())

            item1.issue_instances(3)
            self.db.session.commit()

            # All the capacity went from item1
            self.assertEqual(0, item1.get_total_remaining_capacity())

            # Change due to item1 will have propagated to the parent
            self.assertEqual(0, parent.remaining_capacity())
            self.assertEqual(0, parent.remaining_capacity())

            # item2 still has capacity but is limited by its parent
            self.assertEqual(sys.maxsize, item2.remaining_capacity())
            self.assertEqual(0, item2.get_total_remaining_capacity())

    def test_flag_propagation(self):
        with self.app.app_context():
            parent = self.get_item(self.parent_name)

            for flag in ['allow_check_in', 'allow_badge_up', 'is_visible', 'is_transferable']:
                parent_value = getattr(parent, flag)

                group1 = ProductGroup(flag, parent=parent)
                self.assertEqual(getattr(group1, flag), parent_value)

                group2 = ProductGroup('!' + flag, parent=parent, **{flag: not parent_value})

                self.assertEqual(getattr(group2, flag), not parent_value)


    def test_token(self):
        with self.app.app_context():
            parent = self.get_item(name=self.parent_name)
            parent.discount_token = 'test'

            item = self.get_item(name=self.group1_name)

            # A token is required by the parent
            with self.assertRaises(ProductGroupException):
                item.issue_instances()

            item.issue_instances(token='test')
            self.assertEqual(1, item.capacity_used)

            with self.assertRaises(ProductGroupException):
                ProductGroup('Bad group', parent=parent, discount_token='double-up')

    def test_get_cheapest(self):
        with self.app.app_context():
            item1 = self.get_item(name=self.group1_name)
            price1 = Price(price_tier=item1, currency='gbp', price_int=5)

            item2 = self.get_item(name=self.group2_name)
            price2 = Price(price_tier=item2, currency='gbp', price_int=500)

            self.db.session.add(price1)
            self.db.session.add(price2)
            self.db.session.commit()

            parent = self.get_item(name=self.parent_name)

            self.assertEqual(item1, parent.get_cheapest('gbp'))


class ProductInstanceTest(unittest.TestCase):
    pg_name = 'pg'
    tier_name = 'tier'
    user_email = 'a@b.c'

    def get_instance(self, session, tier=None):
        user = User.get_by_email(self.user_email)
        if tier is None:
            tier = PriceTier.get_by_name(self.tier_name)

        instance = ProductInstance.create_instances(user, tier, 'gbp')[0]

        session.add(instance)
        session.commit()

        return instance

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

        with self.app.app_context():

            user = User(self.user_email, 'test_user')
            self.db.session.add(user)

            parent = ProductGroup(self.pg_name, capacity_max=3, allow_check_in=False)
            tier = PriceTier(self.tier_name, parent=parent)
            price = Price(price_tier=tier, currency="gbp", price_int=666)
            # These have `cascade=all` so just add the bottom of the hierarchy
            self.db.session.add(price)

            self.db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            for inst in User.get_by_email(self.user_email).products:
                self.db.session.delete(inst)

            for inst in User.get_by_email(self.user_email).purchases:
                self.db.session.delete(inst)

            self.db.session.delete(User.get_by_email(self.user_email))
            self.db.session.delete(ProductGroup.get_by_name(self.pg_name))
            self.db.session.commit()

    def test_create_instances(self):
        with self.app.app_context():
            user = User.get_by_email(self.user_email)
            tier = PriceTier.get_by_name(self.tier_name)
            self.assertEqual(0, tier.capacity_used)

            instance = self.get_instance(self.db.session)

            self.assertEqual(1, tier.capacity_used)
            self.assertEqual(1, ProductGroup.get_by_name(self.pg_name).capacity_used)

            # NB: Decimal('6.66') != Decimal(6.66) == Decimal(float(6.66)) ~= 6.6600000000000001
            self.assertEqual(instance.price.value, Decimal('6.66'))

            # Test issuing multiple instances works
            more_instances = ProductInstance.create_instances(user, tier, 'gbp', 2)
            self.assertEqual(2, len(more_instances))
            self.assertEqual(3, ProductGroup.get_by_name(self.pg_name).capacity_used)

            # Test issuing beyond capacity errors
            with self.assertRaises(ProductGroupException):
                ProductInstance.create_instances(user, tier, 'gbp')

    def test_product_instance_state_machine(self):
        states_dict = PRODUCT_INSTANCE_STATES

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
            instance = self.get_instance(self.db.session)

            with self.assertRaises(ProductInstanceStateException):
                instance.set_state('disallowed-state')

            with self.assertRaises(ProductInstanceStateException):
                instance.set_state('paid')

            instance.set_state('payment-pending')

            self.assertEqual('payment-pending', instance.state)

    def test_product_group_get_counts_by_state(self):
        with self.app.app_context():
            # Test it works at the PriceTier level
            tier1 = PriceTier.get_by_name(self.tier_name)
            instance1 = self.get_instance(self.db.session)

            states_count = tier1.get_counts_by_state()
            expect = {s: 0 for s in PRODUCT_INSTANCE_STATES.keys()}
            expect['reserved'] = 1

            self.assertEqual(expect, states_count)

            # Now test we see the same in a ProductGroup
            parent = ProductGroup.get_by_name(self.pg_name)

            parent_states = parent.get_counts_by_state()

            self.assertEqual(expect, parent_states)

            # Test that other states show up
            instance1.set_state('payment-pending')
            self.db.session.commit()

            parent_states = parent.get_counts_by_state()
            expect['reserved'] = 0
            expect['payment-pending'] = 1

            self.assertEqual(expect, parent_states)

            # Add another instance in another tier
            tier2 = PriceTier('2', parent=parent)
            price = Price(price_tier=tier2, currency="gbp", price_int=666)
            self.db.session.add(price)
            # rely on the commit in 'get_instance'
            self.get_instance(self.db.session, tier2)

            parent_states = parent.get_counts_by_state()
            expect['reserved'] = 1

            self.assertEqual(expect, parent_states)

    def test_get_sold(self):
        with self.app.app_context():
            # Test it works at the PriceTier level
            tier = PriceTier.get_by_name(self.tier_name)
            instance = self.get_instance(self.db.session)
            expect = {s: 0 for s in bought_states}

            instance.state = 'paid'
            expect['paid'] = 1

            self.assertEqual(expect, tier.get_sold())

            parent = ProductGroup.get_by_name(self.pg_name)
            self.assertEqual(expect, parent.get_sold())

    def test_user_limit(self):
        with self.app.app_context():
            user = User.get_by_email(self.user_email)
            tier = PriceTier.get_by_name(self.tier_name)
            tier.personal_limit = 1

            self.db.session.commit()

            self.assertEqual(1, tier.user_limit(user))

            self.get_instance(self.db.session)

            self.assertEqual(0, tier.user_limit(user))
            self.assertTrue(tier.has_capacity())

    def test_check_in(self):
        with self.app.app_context():
            # Test it works at the PriceTier level
            instance = self.get_instance(self.db.session)

            instance.state = 'receipt-emailed'

            with self.assertRaises(ProductGroupException):
                instance.check_in()

            tier = PriceTier.get_by_name(self.tier_name)
            tier.allow_check_in = True
            self.db.session.commit()

            instance.check_in()
            self.assertEqual('checked-in', instance.state)


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

            tier = PriceTier(self.pg_name, allow_check_in=True)
            price = Price(price_tier=tier, currency="gbp", price_int=666)
            # These have `cascade=all` so just add the bottom of the hierarchy
            self.db.session.add(price)
            self.db.session.commit()

            # PriceTier needs to have been committed before this
            instance = ProductInstance.create_instances(user1, tier, 'gbp')[0]
            self.db.session.add(instance)

            self.db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            for inst in User.get_by_email(self.user1_email).products:
                self.db.session.delete(inst)

            for inst in User.get_by_email(self.user1_email).purchases:
                self.db.session.delete(inst)

            for inst in User.get_by_email(self.user2_email).products:
                self.db.session.delete(inst)

            for inst in User.get_by_email(self.user2_email).purchases:
                self.db.session.delete(inst)

            self.db.session.delete(User.get_by_email(self.user1_email))
            self.db.session.delete(User.get_by_email(self.user2_email))
            self.db.session.delete(ProductGroup.get_by_name(self.pg_name))
            self.db.session.commit()

    def test_transfer(self):
        with self.app.app_context():
            user1 = User.get_by_email(self.user1_email)
            user2 = User.get_by_email(self.user2_email)
            item = user1.purchases[0]

            item.price_tier.allow_check_in = True
            item.price_tier.is_transferable = False

            with self.assertRaises(ProductTransferException) as e:
                item.transfer(user1, user2, self.db.session)
                self.assertIn('not transferable', e.args[0])

            with self.assertRaises(ProductTransferException) as e:
                item.transfer(user2, user1, self.db.session)

                self.assertIn('does not own this item', e.args[0])

            self.db.session.commit()
            item.price_tier.is_transferable = True

            with self.assertRaises(ProductTransferException) as e:
                item.transfer(user1, user1, self.db.session)

                self.assertIn('users must be different', e.args[0])

            item.transfer(user1, user2, self.db.session)
            self.db.session.commit()

            self.assertEqual(item.owner_id, user2.id)
            self.assertEqual(item.purchaser_id, user1.id)

            item.state = 'checked-in'
            self.db.session.commit()

            self.assertEqual(item, user2.get_tickets()[0])
            self.assertNotIn(item, user1.get_tickets())

            xfer = item.transfers[0]

            self.assertEqual(xfer.to_user.id, user2.id)
            self.assertEqual(xfer.from_user.id, user1.id)

