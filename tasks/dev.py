
import random
from faker import Faker
from flask_script import Command

from main import db
from models.cfp import TalkProposal
from models.user import User
from models.product import Product
from models.purchase import Purchase


class CreateDB(Command):
    # For testing - you usually want to use db migrate/db upgrade instead
    def run(self):
        db.create_all()


class MakeFakeUsers(Command):
    def run(self):
        if not User.query.filter_by(email='admin@test.invalid').first():
            user = User('admin@test.invalid', 'Test Admin')
            user.grant_permission('admin')
            cfp = TalkProposal()
            cfp.user = user
            cfp.title = 'test (admin)'
            cfp.description = 'test proposal from admin'
            db.session.add(user)

        if not User.query.filter_by(email='anonymiser@test.invalid').first():
            user2 = User('anonymiser@test.invalid', 'Test Anonymiser')
            user2.grant_permission('cfp_anonymiser')
            cfp = TalkProposal()
            cfp.user = user2
            cfp.title = 'test (anonymiser)'
            cfp.description = 'test proposal from anonymiser'
            db.session.add(user2)

        if not User.query.filter_by(email='reviewer@test.invalid').first():
            user3 = User('reviewer@test.invalid', 'Test Reviewer')
            user3.grant_permission('cfp_reviewer')
            cfp = TalkProposal()
            cfp.user = user3
            cfp.title = 'test (reviewer)'
            cfp.description = 'test proposal from reviewer'
            db.session.add(user3)

        if not User.query.filter_by(email='arrivals@test.invalid').first():
            user4 = User('arrivals@test.invalid', 'Test Arrivals')
            user4.grant_permission('arrivals')
            cfp = TalkProposal()
            cfp.user = user4
            cfp.title = 'test (arrivals)'
            cfp.description = 'test proposal from arrivals'
            db.session.add(user4)

        db.session.commit()


class MakeFakeTickets(Command):
    def run(self):
        faker = Faker()
        for i in range(1500):
            user = User('user_%s@test.invalid' % i, faker.name())
            db.session.add(user)
            db.session.commit()

        for user in User.query.all():
            try:
                # Choose a random number and type of tickets for this user

                full_count = random.choice([1] * 3 + [2, 3])
                full_type = Product.get_by_name('general', 'full').get_cheapest()
                full_tickets = Purchase.create_purchases(user, full_type, 'GBP', full_count)


                kids_count = random.choice([0] * 10 + [1, 2])
                kids_type = Product.get_by_name('general', random.choice('u5', 'u16')).get_cheapest()
                kids_tickets = Purchase.create_purchases(user, kids_type, 'GBP', kids_count)

                vehicle_count = random.choice([0] * 2 + [1])
                vehicle_type = Product.get_by_name('general', random.choice('parking', 'campervan')).get_cheapest()
                vehicle_tickets = Purchase.create_purchases(user, vehicle_type, 'GBP', vehicle_count)

                for t in full_tickets + kids_tickets + vehicle_tickets:
                    db.session.add(t)
                    t.state = random.choice(['paid'] * 4 + ['expired'] + ['refunded'])

            except:
                db.session.rollback()
                raise

            db.session.commit()

