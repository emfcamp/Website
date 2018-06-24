import random
from faker import Faker
from flask_script import Command

from main import db
from models.cfp import (TalkProposal, PerformanceProposal, WorkshopProposal,
                        YouthWorkshopProposal, InstallationProposal, CFPVote,
                        LENGTH_OPTIONS)
from models.user import User

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
                vote.vote = random.randint(0, 3)

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
