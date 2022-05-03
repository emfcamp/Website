import random
from faker import Faker

from apps.cfp.scheduler import Scheduler
from main import db
from models.user import User
from models.basket import Basket
from models.product import PriceTier
from models.payment import StripePayment, BankPayment
from models.cfp import (
    TalkProposal,
    PerformanceProposal,
    WorkshopProposal,
    YouthWorkshopProposal,
    InstallationProposal,
    CFPVote,
    LENGTH_OPTIONS,
)

from models.volunteer.volunteer import Volunteer
from models.map import MapObject


def random_state(states):
    cumulative = []
    p = 0
    for state, prob in states.items():
        cumulative.append((state, p + prob))
        p += prob
    assert round(p, 3) == 1

    r = random.random()
    for state, prob in cumulative:
        if r <= prob:
            return state
    assert False


def randombool(probability):
    return random.random() < probability


def fake_location():
    # Rough Lat and Lon ranges of Eastnor
    lon_range = (-2.37509, -2.38056)
    lat_range = (52.0391, 52.0438)
    return "SRID=4326;POINT({lon} {lat})".format(
        lon=random.uniform(*lon_range), lat=random.uniform(*lat_range)
    )


def fake_proposal(fake, reviewers):
    cfp = random.choice(
        [
            TalkProposal,
            PerformanceProposal,
            WorkshopProposal,
            YouthWorkshopProposal,
            InstallationProposal,
        ]
    )()
    cfp.title = fake.sentence(nb_words=6, variable_nb_words=True)
    cfp.description = fake.text(max_nb_chars=500)
    cfp.requirements = fake.sentence(nb_words=10, variable_nb_words=True)
    cfp.needs_help = random.random() < 0.2
    cfp.needs_money = random.random() < 0.2
    cfp.one_day = random.random() < 0.2

    if type(cfp) in (TalkProposal, WorkshopProposal):
        cfp.length = random.choice(LENGTH_OPTIONS)[0]

    states = {
        "accepted": 0.1,
        "rejected": 0.05,
        "anonymised": 0.1,
        "checked": 0.15,
        "anon-blocked": 0.05,
        "new": 0.05,
        "reviewed": 0.2,
        "finished": 0.3,
    }

    cfp.state = random_state(states)

    vote_states = {
        "voted": 0.65,
        "recused": 0.1,
        "blocked": 0.05,
        "resolved": 0.1,
        "stale": 0.1,
    }

    if cfp.state in ("anonymised", "reviewed", "accepted") and type(cfp) in (
        TalkProposal,
        WorkshopProposal,
    ):
        for reviewer in random.sample(reviewers, random.randint(0, len(reviewers))):
            vote = CFPVote(reviewer, cfp)
            vote.state = random_state(vote_states)
            if vote.state in ("voted", "stale", "resolved"):
                vote.vote = random.randint(0, 2)

    if cfp.state == "finished" and type(cfp) is TalkProposal:
        cfp.available_times = "fri_13_16,fri_16_20,sat_10_13,sat_13_16,sat_16_20,sun_10_13,sun_13_16,sun_16_20"

    if type(cfp) in (WorkshopProposal, YouthWorkshopProposal):
        cfp.attendees = int(round(random.uniform(5, 50)))
    return cfp


class FakeDataGenerator(object):
    def __init__(self):
        self.fake = Faker("en_GB")

    def run(self):
        if not User.query.filter_by(email="admin@test.invalid").first():
            user_admin = User("admin@test.invalid", "Test Admin")
            user_admin.grant_permission("admin")
            db.session.add(user_admin)

        if not User.query.filter_by(email="cfp_admin@test.invalid").first():
            user_cfp_admin = User("cfp_admin@test.invalid", "Test CFP Admin")
            user_cfp_admin.grant_permission("cfp_admin")
            db.session.add(user_cfp_admin)

        if not User.query.filter_by(email="anonymiser@test.invalid").first():
            user_anonymiser = User("anonymiser@test.invalid", "Test Anonymiser")
            user_anonymiser.grant_permission("cfp_anonymiser")
            db.session.add(user_anonymiser)

        reviewers = []
        for i in range(10):
            email = "reviewer{}@test.invalid".format(i)
            user = User.query.filter_by(email=email).first()
            if not user:
                user = User(email, "Reviewer {}".format(i))
                user.grant_permission("cfp_reviewer")
                db.session.add(user)
            reviewers.append(user)

        if not User.query.filter_by(email="arrivals@test.invalid").first():
            user_arrivals = User("arrivals@test.invalid", "Test Arrivals")
            user_arrivals.grant_permission("arrivals")
            db.session.add(user_arrivals)

        for i in range(0, 160):
            email = self.fake.safe_email()
            if User.get_by_email(email):
                continue
            user = User(email, self.fake.name())

            for i in range(0, int(round(random.uniform(0, 2)))):
                cfp = fake_proposal(self.fake, reviewers)
                cfp.user = user

            if randombool(0.2):
                self.create_volunteer_data(user)

            if randombool(0.2):
                self.create_map_object(user)

            db.session.add(user)
            self.create_fake_tickets(user)

            db.session.commit()

        scheduler = Scheduler()
        scheduler.set_rough_durations()

    def create_map_object(self, user):
        obj = MapObject()
        obj.owner = user
        obj.name = self.fake.text(max_nb_chars=20)
        obj.geom = fake_location()
        obj.wiki_page = "Village:Fake Village"
        db.session.add(obj)

    def create_volunteer_data(self, user):
        vol = Volunteer()
        vol.user = user
        vol.missing_shifts_opt_in = randombool(0.5)
        vol.banned = randombool(0.05)
        vol.volunteer_phone = self.fake.phone_number()
        vol.over_18 = randombool(0.2)
        vol.allow_comms_during_event = randombool(0.8)
        vol.volunteer_email = user.email
        vol.nickname = user.name
        db.session.add(vol)

    def create_fake_tickets(self, user):
        if random.random() < 0.3:
            return

        if random.random() < 0.2:
            currency = "EUR"
        else:
            currency = "GBP"
        b = Basket(user, currency)

        pt = PriceTier.query.filter_by(name="full-std").one()
        b[pt] = int(round(random.uniform(1, 4)))

        if random.random() < 0.5:
            pt = PriceTier.query.filter_by(name="parking").one()
            b[pt] = 1

        b.create_purchases()
        b.ensure_purchase_capacity()

        payment_type = {"bank": BankPayment, "stripe": StripePayment}.get(
            random_state({"bank": 0.2, "stripe": 0.8})
        )

        payment = b.create_payment(payment_type)

        if random.random() < 0.8:
            payment.paid()
        else:
            payment.cancel()
