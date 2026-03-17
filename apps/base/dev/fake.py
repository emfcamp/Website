import logging
import random
from collections.abc import Mapping
from fractions import Fraction
from typing import TypeVar, get_args

from faker import Faker
from flask import current_app as app
from sqlalchemy import select

from main import db
from models import Currency
from models.basket import Basket
from models.cfp import (
    DURATION_OPTIONS,
    ROUGH_DURATIONS,
    InstallationAttributes,
    LightningTalkAttributes,
    Occurrence,
    PerformanceAttributes,
    Proposal,
    ProposalType,
    ProposalVote,
    ProposalWorkshopAttributes,
    ProposalYouthWorkshopAttributes,
    ScheduleItem,
    TalkAttributes,
    WorkshopAttributes,
    YouthWorkshopAttributes,
)
from models.diversity import (
    AGE_CHOICES,
    DISABILITY_CHOICES,
    ETHNICITY_CHOICES,
    GENDER_CHOICES,
    SEXUALITY_CHOICES,
    UserDiversity,
)
from models.lottery import Lottery, LotteryEntry, LotteryState, get_max_rank_for_user
from models.payment import BankPayment, StripePayment
from models.product import PriceTier
from models.user import User
from models.village import Village, VillageMember, VillageRequirements
from models.volunteer.volunteer import Volunteer

logger = logging.getLogger(__name__)


T = TypeVar("T")


def random_choice[T](population_weights: Mapping[T, float | Fraction]) -> T:
    population = list(population_weights.keys())
    weights = list(population_weights.values())
    choices = random.choices(population, weights=weights)
    return choices[0]


def random_bool(probability: float | Fraction) -> bool:
    return random.random() < probability


def fake_location() -> str:
    # Rough Lat and Lon ranges of Eastnor
    lon = random.uniform(-2.37509, -2.38056)
    lat = random.uniform(52.0391, 52.0438)
    return f"SRID=4326;POINT({lon} {lat})"


class FakeDataGenerator:
    def __init__(self):
        self.fake = Faker("en_GB")

    def create_users(self) -> None:
        all_users: list[User] = list(db.session.scalars(select(User)).unique())

        def get_user(email: str) -> User | None:
            users = [u for u in all_users if u.email == email]
            if users:
                return users[0]
            return None

        self.admin = get_user("admin@test.invalid")
        if not self.admin:
            self.admin = User("admin@test.invalid", "Test Admin")
            self.admin.grant_permission("admin")
            db.session.add(self.admin)

        self.cfp_admins = []
        for i in range(4):
            email = f"cfp_admin{i + 1}@test.invalid"
            user = get_user(email)
            if not user:
                user = User(email, f"Test CFP Admin {i + 1}")
                user.grant_permission("cfp_admin")
                db.session.add(user)
            self.cfp_admins.append(user)

        self.anonymiser = get_user("anonymiser@test.invalid")
        if not self.anonymiser:
            self.anonymiser = User("anonymiser@test.invalid", "Test Anonymiser")
            self.anonymiser.grant_permission("cfp_anonymiser")
            db.session.add(self.anonymiser)

        self.arrivals_users = get_user("arrivals@test.invalid")
        if not self.arrivals_users:
            self.arrivals_users = User("arrivals@test.invalid", "Test Arrivals")
            self.arrivals_users.grant_permission("arrivals")
            db.session.add(self.arrivals_users)

        self.reviewers = []
        for i in range(10):
            email = f"reviewer{i + 1}@test.invalid"
            user = get_user(email)
            if not user:
                user = User(email, f"Reviewer {i + 1}")
                user.grant_permission("cfp_reviewer")
                db.session.add(user)
            self.reviewers.append(user)

        # We have a fixed set of well-known users, but create more normal users each time
        self.users: list[User] = []
        while len(self.users) < 120:
            email = self.fake.safe_email()
            user = get_user(email)
            if user:
                app.logger.warning(f"User found with email address matching fake {email}, skipping")
                continue

            user = User(email, self.fake.name())
            db.session.add(user)
            self.users.append(user)

    def create_proposal(self, user: User, reviewers: list[User]) -> Proposal:
        states = {
            "new": 0.05,
            "edit": 0.2,
            "checked": 0.15,
            "rejected": 0.05,
            "anonymised": 0.1,
            "anon-blocked": 0.05,
            "manual-review": 0.05,
            "reviewed": 0.2,
            "accepted": 0.1,
            "finalised": 0.3,
            "withdrawn": 0.05,
        }

        proposal = Proposal(
            # TODO: weightings for type
            type=random.choice(get_args(ProposalType)),
            state=random_choice(states),
            user=user,
            title=self.fake.sentence(nb_words=6, variable_nb_words=True),
            description=self.fake.text(max_nb_chars=500),
            # duration below
            needs_help=random_bool(0.2),
            equipment_required=self.fake.sentence(nb_words=10, variable_nb_words=True),
            # funding_required
            # notice_required
            # additional_info
            needs_money=random_bool(0.2),
            one_day=random_bool(0.2),
            # rejected_email_sent
        )

        if proposal.type not in {"installation"}:
            proposal.duration = random.choice(DURATION_OPTIONS)[0]

        vote_states = {
            # new
            "voted": 0.65,
            "recused": 0.1,
            "blocked": 0.05,
            "resolved": 0.1,
            "stale": 0.1,
        }

        if proposal.state in {"anonymised", "reviewed", "accepted"} and proposal.type in {"talk", "workshop"}:
            for reviewer in random.sample(reviewers, random.randint(0, len(reviewers))):
                vote = ProposalVote(reviewer, proposal)
                vote.state = random_choice(vote_states)
                if vote.state in ("voted", "stale", "resolved"):
                    vote.vote = random.randint(0, 2)

        if isinstance(proposal.attributes, ProposalWorkshopAttributes):
            proposal.attributes.participant_count = str(random.randint(5, 50))
        elif isinstance(proposal.attributes, ProposalYouthWorkshopAttributes):
            proposal.attributes.participant_count = str(random.randint(5, 50))

        db.session.add(proposal)
        return proposal

    def create_schedule_item(
        self, *, official_content: bool = True, user: User | None = None, proposal: Proposal | None = None
    ) -> ScheduleItem:
        states = {
            "published": 7,
            "unpublished": 2,
            "hidden": 1,
        }

        pronoun_choices = {
            "he/him": 0.5,
            "she/her": 0.4,
            "they/them": 0.2,
            "he/they": 0.1,
            "she/they": 0.1,
        }

        name_count = random.randint(1, 3)
        names = ", ".join(self.fake.name() for _ in range(name_count))
        pronouns = ", ".join(random_choice(pronoun_choices) for _ in range(name_count))
        title = self.fake.sentence(nb_words=6, variable_nb_words=True)
        description = self.fake.text(max_nb_chars=500)

        if proposal:
            if random_bool(0.9):
                names = proposal.user.name
                pronouns = random_choice(pronoun_choices)
            if random_bool(0.9):
                title = proposal.title
            if random_bool(0.9):
                description = proposal.description

        schedule_item = ScheduleItem(
            # TODO: weightings for type
            # No lightning talks yet
            type=random.choice(["talk", "performance", "workshop", "youthworkshop", "installation"]),
            state=random_choice(states),
            user=user,
            proposal=proposal,
            names=names,
            pronouns=pronouns,
            title=title,
            description=description,
            short_description=self.fake.sentence(nb_words=20, variable_nb_words=True),
            official_content=official_content,
            default_video_privacy=random_choice({"public": 0.8, "review": 0.1, "none": 0.1}),
            # arrival_period
            # departure_period
            available_times="fri_10_13,fri_13_16,fri_16_20,sat_10_13,sat_13_16,sat_16_20,sun_10_13,sun_13_16,sun_16_20",
            # contact_telephone
            # contact_eventphone
        )

        if isinstance(schedule_item.attributes, TalkAttributes):
            schedule_item.attributes.content_note = self.fake.sentence(nb_words=10, variable_nb_words=True)
            schedule_item.attributes.family_friendly = random_bool(0.2)
            schedule_item.attributes.needs_laptop = random_bool(0.1)

        elif isinstance(schedule_item.attributes, PerformanceAttributes):
            pass

        elif isinstance(schedule_item.attributes, WorkshopAttributes | YouthWorkshopAttributes):
            schedule_item.attributes.age_range = self.fake.text(max_nb_chars=20)
            schedule_item.attributes.participant_cost = self.fake.text(max_nb_chars=10)
            schedule_item.attributes.participant_equipment = self.fake.text(max_nb_chars=50)
            schedule_item.attributes.content_note = self.fake.sentence(nb_words=10, variable_nb_words=True)
            if isinstance(schedule_item.attributes, WorkshopAttributes):
                schedule_item.attributes.family_friendly = random_bool(0.2)

        elif isinstance(schedule_item.attributes, InstallationAttributes):
            schedule_item.attributes.size = self.fake.text(max_nb_chars=40)

        elif isinstance(schedule_item.attributes, LightningTalkAttributes):
            # Not implemented yet
            pass

        db.session.add(schedule_item)

        # The overwhelming majority have 1 occurrence
        occurrence_count = random_choice(
            {
                0: 5,
                1: 100,
                2: 10,
                3: 5,
                4: 5,
            }
        )

        if schedule_item.type_info.needs_occurrence:
            for occurrence_num in range(1, occurrence_count):
                self.create_occurrence(schedule_item, occurrence_num)

        return schedule_item

    def create_occurrence(self, schedule_item: ScheduleItem, occurrence_num: int) -> Occurrence:
        # TODO: implement scheduling?
        occurrence = Occurrence(
            state="unscheduled",
            schedule_item=schedule_item,
            occurrence_num=occurrence_num,
            manually_scheduled=random_bool(0.9),
            scheduled_duration=random.choice(list(ROUGH_DURATIONS.values())),
            # allowed_times
            # potential_time
            # potential_venue_id
            # scheduled_time
            # scheduled_venue_id
            video_privacy=schedule_item.default_video_privacy,
            # c3voc_url
            # youtube_url
            # thumbnail_url
            # video_recording_lost
        )
        db.session.add(occurrence)

        if schedule_item.type_info.supports_lottery and random_bool(0.7):
            participant_count = random.randint(10, 15)
            occurrence.lottery = Lottery(
                # TODO: weightings for state
                state=random.choice(get_args(LotteryState)),
                occurrence=occurrence,
                total_tickets=participant_count + 10,
                # reserved_tickets
                max_tickets_per_entry=schedule_item.type_info.default_max_tickets_per_entry,
            )

            db.session.add(occurrence.lottery)

            participants = random.sample(self.users, participant_count)
            self.create_lottery_entries(occurrence.lottery, participants)

        return occurrence

    def create_village(self, user):
        village = Village(
            name=self.fake.text(max_nb_chars=20),
            description=self.fake.text(max_nb_chars=100),
        )

        if random_bool(0.5):
            village.location = fake_location()

        db.session.add(village)

        reqs = VillageRequirements(
            village=village,
            num_attendees=random.randint(2, 100),
        )
        db.session.add(reqs)

        membership = VillageMember(
            user=user,
            village=village,
            admin=True,
        )
        db.session.add(membership)

    def create_volunteer_data(self, user):
        vol = Volunteer(
            user=user,
            nickname=user.name,
            banned=random_bool(0.05),
            volunteer_phone=self.fake.phone_number(),
            volunteer_email=user.email,
            over_18=random_bool(0.2),
            allow_comms_during_event=random_bool(0.8),
        )
        db.session.add(vol)

        user.grant_permission("volunteer:user")

    def create_lottery_entries(self, lottery: Lottery, users: list[User]) -> None:
        for user in users:
            rank = get_max_rank_for_user(user, lottery.schedule_item.type)
            lottery_entry = LotteryEntry(
                state="entered",
                user=user,
                lottery=lottery,
                ticket_count=random.randint(1, lottery.max_tickets_per_entry),
                rank=rank,
            )
            db.session.add(lottery_entry)

    def create_diversity_data(self, user):
        diversity = UserDiversity(
            user=user,
            age=random.choice(AGE_CHOICES)[0],
            gender=random.choice(GENDER_CHOICES)[0],
            ethnicity=random.choice(ETHNICITY_CHOICES)[0],
            disability=random.choice(DISABILITY_CHOICES)[0],
            sexuality=random.choice(SEXUALITY_CHOICES)[0],
        )
        db.session.add(diversity)

    def create_admission_tickets_and_commit(self, user: User) -> None:
        currency = random_choice({Currency.EUR: 0.2, Currency.GBP: 0.8})

        # In this case we're going to use the same payment method if we make multiple payments.
        payment_cls = random_choice({BankPayment: 0.2, StripePayment: 0.8})

        payment_count = round(random.gauss(0, 2))
        for _ in range(0, payment_count):
            basket = Basket(user, currency)
            pt = db.session.execute(select(PriceTier).where(PriceTier.name == "full-std")).scalar_one()
            basket[pt] = random.randint(1, 4)

            if random_bool(0.2):
                pt = db.session.execute(select(PriceTier).where(PriceTier.name == "parking")).scalar_one()
                basket[pt] = 1

            basket.create_purchases()
            basket.ensure_purchase_capacity()

            payment = basket.create_payment(payment_cls)
            assert payment is not None

            db.session.add(payment)

            # Commit in-line so we get the state changes in history
            db.session.commit()

            if random_bool(0.2):
                payment.cancel()
                db.session.commit()
                continue

            payment.paid()
            db.session.commit()

            if random_bool(0.2):
                payment.manual_refund()
                db.session.commit()

    def run(self):
        self.create_users()

        for user in self.users:
            # NB not all users will have a proposal
            # These numbers aren't realistic, we just want some variety
            proposal_count = random_choice({0: 0.25, 1: 0.5, 2: 0.25})
            for _ in range(proposal_count):
                proposal = self.create_proposal(user, self.reviewers)

                if proposal.state in {"accepted", "finalised"}:
                    self.create_schedule_item(
                        official_content=True,
                        user=proposal.user,
                        proposal=proposal,
                    )

            if random_bool(0.8):
                self.create_diversity_data(user)

            if random_bool(0.5):
                self.create_volunteer_data(user)

            if random_bool(0.5):
                self.create_village(user)

        for _ in range(40):
            # Some unparented schedule items, created by the CFP team
            self.create_schedule_item(
                official_content=True,
                user=random.choice(self.cfp_admins),
            )

        for _ in range(40):
            # Attendee content
            # Some of this will be managed by people who are associated with official content too
            self.create_schedule_item(
                official_content=False,
                user=random.choice(self.users),
            )

        db.session.commit()

        # This does lots of committing, so we do it separately
        for user in self.users:
            self.create_admission_tickets_and_commit(user)
