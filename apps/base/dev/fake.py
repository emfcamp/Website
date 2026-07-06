import logging
import random
from collections.abc import Mapping
from datetime import datetime, time, timedelta
from fractions import Fraction
from typing import TypeVar, cast

from faker import Faker
from flask import current_app as app
from sqlalchemy import select

from apps.config import config
from main import db
from models import Currency
from models.basket import Basket
from models.content import (
    DURATION_OPTIONS,
    Occurrence,
    Proposal,
    ProposalType,
    ProposalVote,
    ScheduleItem,
)
from models.content.attributes import (
    FamilyWorkshopAttributes,
    InstallationAttributes,
    LightningTalkAttributes,
    PerformanceAttributes,
    ProposalFamilyWorkshopAttributes,
    ProposalWorkshopAttributes,
    TalkAttributes,
    WorkshopAttributes,
)
from models.content.cfp import ROUGH_DURATIONS, ProposalState
from models.content.lottery import (
    Lottery,
    LotteryEntry,
    LotteryState,
    get_max_rank_for_user,
)
from models.content.schedule import ScheduleItemAvailability, ScheduleItemType
from models.content.venue import Venue
from models.diversity import (
    AGE_CHOICES,
    DISABILITY_CHOICES,
    ETHNICITY_CHOICES,
    GENDER_CHOICES,
    SEXUALITY_CHOICES,
    UserDiversity,
)
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

    def fake_title(self, *args, **kwargs) -> str:  # type: ignore[no-untyped-def]
        title: str = self.fake.sentence(*args, **kwargs)
        return title.removesuffix(".")

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
            self.create_admission_tickets_and_commit(self.admin)

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
        while len(self.users) < 250:
            email = self.fake.safe_email()
            user = get_user(email)
            if user or any(u for u in self.users if u.email == email):
                app.logger.warning(f"User found with email address matching fake {email}, skipping")
                continue

            user = User(email, self.fake.name())
            db.session.add(user)
            self.users.append(user)

    def create_proposal(self, user: User, reviewers: list[User]) -> Proposal:
        states: dict[ProposalState, float] = {
            "new": 5,
            "edit": 5,
            "checked": 10,
            "rejected": 5,
            "anonymised": 10,
            "anon-blocked": 5,
            "manual-review": 5,
            "accepted": 30,
            "finalised": 60,
            "withdrawn": 5,
        }

        types: dict[ProposalType, float] = {
            "talk": 500,
            "installation": 200,
            "workshop": 200,
            "performance": 100,
            "familyworkshop": 50,
        }

        proposal = Proposal(
            type=random_choice(types),
            state="new",
            user=user,
            title=self.fake_title(nb_words=6, variable_nb_words=True),
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

        created_ago = random.randint(0, 60 * 60 * 24 * 90)
        proposal.created = datetime.now() - timedelta(seconds=created_ago)
        proposal.modified = datetime.now() - timedelta(seconds=random.randint(0, created_ago))

        state = random_choice(states)

        if proposal.type not in {"installation"}:
            proposal.duration = random.choice(DURATION_OPTIONS)[0]

        vote_states = {
            # new
            "voted": 0.65,
            "recused": 0.01,
            "blocked": 0.05,
            "resolved": 0.1,
            "stale": 0.1,
        }

        if state in {"anonymised", "accepted"} and proposal.type in {"talk", "workshop"}:
            for reviewer in random.sample(reviewers, random.randint(0, len(reviewers))):
                vote = ProposalVote(reviewer, proposal)
                vote.state = random_choice(vote_states)
                if vote.state in ("voted", "stale", "resolved"):
                    vote.vote = random.randint(0, 2)
                proposal.votes.append(vote)

        if isinstance(proposal.attributes, ProposalWorkshopAttributes):
            proposal.attributes.participant_count = str(random.randint(5, 50))
            proposal.attributes.drop_in = random_bool(0.5)
        elif isinstance(proposal.attributes, ProposalFamilyWorkshopAttributes):
            proposal.attributes.participant_count = str(random.randint(5, 50))
            proposal.attributes.drop_in = True

        if state in {"accepted", "finalised"}:
            # See Proposal.accept
            if proposal.type_info.schedule:
                self.create_schedule_item(
                    official_content=True,
                    user=proposal.user,
                    proposal=proposal,
                )

            if proposal.type_info.grants_event_tickets:
                proposal.user.issue_cfp_voucher()

        if state == "finalised" and proposal.schedule_item:
            if random_bool(0.95):
                proposal.schedule_item.state = "published"

            proposal.schedule_item.availability = [
                ScheduleItemAvailability(
                    start=datetime.combine(day, time(10)), end=datetime.combine(day, time(20))
                )
                for day in config.event_days
            ]

        proposal.state = state

        db.session.add(proposal)
        return proposal

    def create_schedule_item(
        self,
        *,
        official_content: bool = True,
        user: User | None = None,
        proposal: Proposal | None = None,
        type: ScheduleItemType | None = None,
    ) -> ScheduleItem | None:
        if proposal and proposal.type_info.schedule == False:
            return None

        # TODO: different weighting based on official_content
        types: dict[ScheduleItemType, float] = {
            "talk": 200,
            "workshop": 100,
            "performance": 25,
            "familyworkshop": 10,
            "film": 10,
            "meetup": 10,
            "music": 10,
            "djset": 10,
        }

        if not proposal or proposal.state == "finalised":
            states = {
                "published": 90,
                "unpublished": 5,
                "cancelled": 5,
            }
        elif proposal and proposal.state == "accepted":
            states = {
                "published": 70,
                "unpublished": 20,
                "cancelled": 10,
            }
        else:
            states = {
                "published": 5,
                "unpublished": 90,
                "cancelled": 5,
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
        title = self.fake_title(nb_words=6, variable_nb_words=True)
        description = self.fake.text(max_nb_chars=500)

        if proposal:
            # Most fields match the proposal, but not always
            if random_bool(0.9):
                type = cast(ScheduleItemType, proposal.type)
            if random_bool(0.9):
                names = proposal.user.name
                pronouns = random_choice(pronoun_choices)
            if random_bool(0.9):
                title = proposal.title
            if random_bool(0.9):
                description = proposal.description

        if not type:
            # mypy infers random_choice's type as ScheduleItemType | None without this dance
            random_type: ScheduleItemType = random_choice(types)
            type = random_type

        schedule_item = ScheduleItem(
            # No lightning talks yet
            type=type,
            state=random_choice(states),
            user=user,
            proposal=proposal,
            names=names if type != "film" else "",
            pronouns=pronouns if type != "film" else "",
            title=title,
            description=description,
            short_description=self.fake.sentence(nb_words=20, variable_nb_words=True),
            official_content=official_content,
            video_privacy=random_choice({"public": 90, "review": 3, "none": 7}) if type != "film" else "none",
            # arrival_period
            # departure_period
            # contact_telephone
            # contact_eventphone
        )

        if isinstance(schedule_item.attributes, TalkAttributes):
            schedule_item.attributes.content_note = self.fake.sentence(nb_words=10, variable_nb_words=True)
            schedule_item.attributes.family_friendly = random_bool(0.2)
            schedule_item.attributes.needs_laptop = random_bool(0.1)

        elif isinstance(schedule_item.attributes, PerformanceAttributes):
            pass

        elif isinstance(schedule_item.attributes, WorkshopAttributes | FamilyWorkshopAttributes):
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

        occurrence_counts = {
            1: 100,
            2: 10,
            3: 3,
            4: 1,
            5: 1,
        }

        for occurrence_num in range(random_choice(occurrence_counts)):
            self.create_occurrence(schedule_item, occurrence_num + 1)

        return schedule_item

    def create_occurrence(self, schedule_item: ScheduleItem, occurrence_num: int) -> Occurrence:
        # TODO: implement scheduling?
        # TODO: vary some scheduled_durations?
        occurrence = Occurrence(
            schedule_item=schedule_item,
            occurrence_num=occurrence_num,
            manually_scheduled=random_bool(0.05),
            scheduled_duration=random.choice(list(ROUGH_DURATIONS.values())),
            # allowed_times
            # potential_time
            # potential_venue_id
            # scheduled_time
            # scheduled_venue_id
            # c3voc_url
            # youtube_url
            # thumbnail_url
            # video_recording_lost
        )
        db.session.add(occurrence)

        if schedule_item.type_info.supports_lottery and random_bool(0.9):
            participant_count = random.randint(10, 15)
            lottery_states: dict[LotteryState, float] = {
                "closed": 10,
                "allow-entry": 80,
                # running-lottery
                # completed
                "sign-up-list": 10,
            }
            occurrence.lottery = Lottery(
                state=random_choice(lottery_states),
                occurrence=occurrence,
                total_tickets=participant_count + 10,
                # reserved_tickets
                max_tickets_per_entry=schedule_item.type_info.default_max_tickets_per_entry,
            )

            db.session.add(occurrence.lottery)

            assert self.admin
            participants = random.sample(self.users + [self.admin], participant_count)
            self.create_lottery_entries(occurrence.lottery, participants)

        return occurrence

    def create_village(self, user):
        name = self.fake_title(nb_words=4, variable_nb_words=True)
        if db.session.scalar(select(Village.id).where(Village.name == name)):
            app.logger.warning("Generated a village name that already exists, skipping")
            return

        village = Village(
            name=name,
            description=self.fake.text(max_nb_chars=100),
        )

        if random_bool(0.5):
            village.location = fake_location()

        venue = Venue(
            village=village,
            name=village.name,
        )
        village.venues.append(venue)

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
            available = pt.user_limit(user)
            if available == 0:
                break

            basket[pt] = min(random.randint(1, 4), available)

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

    def run(self) -> None:
        self.create_users()

        for user in self.users:
            # NB not all users will have a proposal
            # These numbers aren't realistic, we just want some variety
            proposal_count = random_choice({0: 0.25, 1: 0.5, 2: 0.25})
            for _ in range(proposal_count):
                self.create_proposal(user, self.reviewers)

            if random_bool(0.8):
                self.create_diversity_data(user)

            if random_bool(0.5):
                self.create_volunteer_data(user)

            if random_bool(0.5):
                self.create_village(user)

        # Schedule items manually created by content team
        # Don't add too many here, the amount of official content
        # is scaled by the number of users, while this isn't.
        official_schedule_items: dict[ScheduleItemType, int] = {
            "film": 2,
            "music": 2,
            "djset": 2,
            "performance": 2,
            "talk": 2,
            "workshop": 1,
            "meetup": 1,
        }
        for type, count in official_schedule_items.items():
            for _ in range(count):
                self.create_schedule_item(
                    official_content=True, user=random.choice(self.cfp_admins), type=type
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
            if user.proposals and random_bool(0.8):
                # Some users with proposals should not have tickets
                continue
            self.create_admission_tickets_and_commit(user)
