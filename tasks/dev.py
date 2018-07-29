import random
from pendulum import parse
from faker import Faker
from flask_script import Command

from main import db
from models.cfp import (TalkProposal, PerformanceProposal, WorkshopProposal,
                        YouthWorkshopProposal, InstallationProposal, CFPVote,
                        LENGTH_OPTIONS)
from models.user import User

from models.volunteer.venue import VolunteerVenue
from models.volunteer.shift import Shift
from models.volunteer.role import Role

def random_state(states):
    cumulative = []
    p = 0
    for state, prob in states.items():
        cumulative.append((state, p + prob))
        p += prob
    assert p == 1

    r = random.random()
    for state, prob in cumulative:
        if r <= prob:
            return state
    assert False


def fake_proposal(fake, reviewers):
    cfp = random.choice([TalkProposal, PerformanceProposal, WorkshopProposal,
                         YouthWorkshopProposal, InstallationProposal])()
    cfp.title = fake.sentence(nb_words=6, variable_nb_words=True)
    cfp.description = fake.text(max_nb_chars=500)
    cfp.requirements = fake.sentence(nb_words=10, variable_nb_words=True)
    cfp.needs_help = random.random() < 0.2
    cfp.needs_money = random.random() < 0.2
    cfp.one_day = random.random() < 0.2

    if type(cfp) in (TalkProposal, WorkshopProposal):
        cfp.length = random.choice(LENGTH_OPTIONS)[0]

    states = {'accepted': 0.1,
              'rejected': 0.05,
              'anonymised': 0.2,
              'checked': 0.2,
              'anon-blocked': 0.05,
              'new': 0.2,
              'reviewed': 0.2}

    cfp.state = random_state(states)

    vote_states = {
        'voted': 0.65,
        'recused': 0.1,
        'blocked': 0.05,
        'resolved': 0.1,
        'stale': 0.1
    }

    if cfp.state in ('anonymised', 'reviewed', 'accepted') and \
            type(cfp) in (TalkProposal, WorkshopProposal):
        for reviewer in random.sample(reviewers, random.randint(0, len(reviewers))):
            vote = CFPVote(reviewer, cfp)
            vote.state = random_state(vote_states)
            if vote.state in ('voted', 'stale', 'resolved'):
                vote.vote = random.randint(0, 2)

    if type(cfp) in (WorkshopProposal, YouthWorkshopProposal):
        cfp.attendees = int(round(random.uniform(5, 50)))
    return cfp


class MakeFakeData(Command):
    def run(self):
        fake = Faker()
        if not User.query.filter_by(email='admin@test.invalid').first():
            user_admin = User('admin@test.invalid', 'Test Admin')
            user_admin.grant_permission('admin')
            db.session.add(user_admin)

        if not User.query.filter_by(email='cfp_admin@test.invalid').first():
            user_cfp_admin = User('cfp_admin@test.invalid', 'Test CFP Admin')
            user_cfp_admin.grant_permission('cfp_admin')
            db.session.add(user_cfp_admin)

        if not User.query.filter_by(email='anonymiser@test.invalid').first():
            user_anonymiser = User('anonymiser@test.invalid', 'Test Anonymiser')
            user_anonymiser.grant_permission('cfp_anonymiser')
            db.session.add(user_anonymiser)

        reviewers = []
        for i in range(10):
            email = 'reviewer{}@test.invalid'.format(i)
            user = User.query.filter_by(email=email).first()
            if not user:
                user = User(email, 'Reviewer {}'.format(i))
                user.grant_permission('cfp_reviewer')
                db.session.add(user)
            reviewers.append(user)

        if not User.query.filter_by(email='arrivals@test.invalid').first():
            user_arrivals = User('arrivals@test.invalid', 'Test Arrivals')
            user_arrivals.grant_permission('arrivals')
            db.session.add(user_arrivals)


        for i in range(0, 500):
            email = fake.safe_email()
            if User.get_by_email(email):
                continue
            user = User(email, fake.name())

            for i in range(0, int(round(random.uniform(0, 2)))):
                cfp = fake_proposal(fake, reviewers)
                cfp.user = user

            db.session.add(user)

        db.session.commit()


class MakeVolunteerData(Command):
    def run(self):
        venue_list = [
            {"name": "Bar", "mapref": "https://map.emfcamp.org/#19/52.0420157/-2.3770749"},
            {"name": "Stage A", "mapref": "https://map.emfcamp.org/#17/52.039601/-2.377759"},
            {"name": "Stage B", "mapref": "https://map.emfcamp.org/#17/52.041798/-2.376412"},
            {"name": "Stage C", "mapref": "https://map.emfcamp.org/#17/52.040482/-2.377432"},
            {"name": "Entrance", "mapref": "https://map.emfcamp.org/#18/52.039226/-2.378184"},
        ]
        role_list = [
            {"name": "Bar", "description": "Serve people booze", "role_notes": "Must be over 18 and complete online training first"},
            {"name": "AV", "description": "Make sure folks giving talks can be heard & their slides seen", "role_notes": ""},
            {"name": "Entrance Steward", "description": "Check tickets and help people get on site.", "role_notes": ""},
        ]

        shift_list = {
            "Bar": {
                "Bar": [
                    {"first": "2018-08-31 11:00:00", "final": "2018-09-01 01:00:00", "min": 2, "max": 5},
                    {"first": "2018-09-01 11:00:00", "final": "2018-09-02 01:00:00", "min": 2, "max": 5},
                    {"first": "2018-09-02 11:00:00", "final": "2018-09-03 00:00:00", "min": 2, "max": 5},
                ]
            },
            "AV": {
                "Stage A": [
                    {"first": "2018-08-31 12:00:00", "final": "2018-09-01 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-02 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 23:00:00", "min": 1, "max": 1},
                ],
                "Stage B": [
                    {"first": "2018-08-31 12:00:00", "final": "2018-09-01 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-02 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 23:00:00", "min": 1, "max": 1},
                ],
                "Stage C": [
                    {"first": "2018-08-31 12:00:00", "final": "2018-09-01 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-02 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 23:00:00", "min": 1, "max": 1},
                ]
            },
            "Entrance Steward": {
                "Entrance": [
                    {"first": "2018-08-31 08:00:00", "final": "2018-09-03 12:00:00", "min": 2, "max": 4},
                ]
            }
        }

        for v in venue_list:
            db.session.add(VolunteerVenue(**v))

        for r in role_list:
            db.session.add(Role(**r))

        for shift_role in shift_list:
            role = Role.get_by_name(shift_role)
            for shift_venue in shift_list[shift_role]:
                venue = VolunteerVenue.get_by_name(shift_venue)

                for shift_ranges in shift_list[shift_role][shift_venue]:
                    shifts = Shift.generate_for(role=role, venue=venue,
                                                first=parse(shift_ranges["first"]),
                                                final=parse(shift_ranges["final"]),
                                                min=shift_ranges["min"], max=shift_ranges["max"])
                    for s in shifts:
                        db.session.add(s)

        db.session.commit()
