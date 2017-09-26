
import random
from faker import Faker
from flask_script import Command

from main import db
from models.cfp import TalkProposal
from models.ticket import Ticket, TicketType, TicketLimitException
from models.user import User


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
                full_type = TicketType.query.filter_by(fixed_id=random.choice([0, 1, 2, 3] * 30 + [9, 10] * 3 + [4])).one()
                full_tickets = [Ticket(user.id, type=full_type) for _ in range(full_count)]

                kids_count = random.choice([0] * 10 + [1, 2])
                kids_type = TicketType.query.filter_by(fixed_id=random.choice([5, 11, 6])).one()
                kids_tickets = [Ticket(user.id, type=kids_type) for _ in range(kids_count)]

                vehicle_count = random.choice([0] * 2 + [1])
                vehicle_type = TicketType.query.filter_by(fixed_id=random.choice([7] * 5 + [8])).one()
                vehicle_tickets = [Ticket(user.id, type=vehicle_type) for _ in range(vehicle_count)]

                for t in full_tickets + kids_tickets + vehicle_tickets:
                    t.paid = random.choice([True] * 4 + [False])
                    t.refunded = random.choice([False] * 20 + [True])

                db.session.commit()

            except TicketLimitException:
                db.session.rollback()
