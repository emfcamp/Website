import random
from pendulum import parse
from faker import Faker
from flask import current_app as app
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
              'anonymised': 0.1,
              'checked': 0.15,
              'anon-blocked': 0.05,
              'new': 0.05,
              'reviewed': 0.2,
              'finished': 0.3}

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

    if cfp.state == 'finished' and type(cfp) is TalkProposal:
        cfp.available_times = 'fri_13_16,fri_16_20,sat_10_13,sat_13_16,sat_16_20,sun_10_13,sun_13_16,sun_16_20'

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
            {"name": "Badge Tent",     "mapref": "https://map.emfcamp.org/#20.24/52.0405486/-2.3781891"},
            {"name": "Bar 2",          "mapref": "https://map.emfcamp.org/#19/52.0409755/-2.3786306"},
            {"name": "Bar",            "mapref": "https://map.emfcamp.org/#19/52.0420157/-2.3770749"},
            {"name": "Car Park",       "mapref": "https://map.emfcamp.org/#19.19/52.0389412/-2.3783488"},
            {"name": "Entrance",       "mapref": "https://map.emfcamp.org/#18/52.039226/-2.378184"},
            {"name": "Green Room",     "mapref": "https://map.emfcamp.org/#20.72/52.0414959/-2.378016"},
            {"name": "Info Desk",      "mapref": "https://map.emfcamp.org/#21.49/52.0415113/-2.3776567"},
            {"name": "Stage A",        "mapref": "https://map.emfcamp.org/#17/52.039601/-2.377759"},
            {"name": "Stage B",        "mapref": "https://map.emfcamp.org/#17/52.041798/-2.376412"},
            {"name": "Stage C",        "mapref": "https://map.emfcamp.org/#17/52.040482/-2.377432"},
            {"name": "Volunteer Tent", "mapref": "https://map.emfcamp.org/#20.82/52.0397817/-2.3767928"},
            {"name": "Youth Workshop", "mapref": "https://map.emfcamp.org/#19.46/52.0420979/-2.3753702"},

            {"name": "N/A",            "mapref": "https://map.emfcamp.org/#16/52.0411/-2.3784"}
        ]
        role_list = [
            # Stage stuff
            {"name": "Herald",                 "description": "Introduce talks and manage speakers at stage."},
            {"name": "Stage: Audio/Visual",    "description": "Run the audio for a stage. Make sure mics are working and that presentations work."},
            {"name": "Stage: Camera Operator", "description": "Point, focus and expose the camera, then lock off shot and monitor it."},
            {"name": "Stage: Vision Mixer",    "description": "Vision mix the output to screen and to stream."},

            # "Tent" roles
            {"name": "Badge Helper",          "description": "Fix, replace and troubleshoot badges and their software."},
            {"name": "Car Parking",           "description": "Help park cars and get people on/off site."},
            {"name": "Catering",              "description": "Help our excellent catering team provide food for all the volunteers."},
            {"name": "Entrance Steward",      "description": "Greet people, check their tickets and help them get on site."},
            {"name": "Games Master",          "description": "Running Indie Games on the big screen in Stage A, and optionally Board Games."},
            {"name": "Green Room",            "description": "Make sure speakers get where they need to be with what they need."},
            {"name": "Info Desk",             "description": "Be a point of contact for attendees. Either helping with finding things or just getting an idea for what's on."},
            {"name": "Tent Steward",          "description": "Check the various tents (e.g. Arcade, Lounge, Spillout) are clean and everything's OK."},
            {"name": "Youth Workshop Helper", "description": "Help support our youth workshop leaders and participants."},

            # Needs training
            {"name": "NOC",                   "description": "Plug/Unplug DKs", "role_notes": "Requires training & the DK Key."},
            {"name": "Bar",                   "description": "Help run the bar. Serve drinks, take payment, keep it clean.", "role_notes": "Requires training, over 18s only.", "over_18_only": True},
            {"name": "Volunteer Manager",     "description": "Help people sign up for volunteering. Make sure they know where to go. Run admin on the volunteer system.", "role_notes": "Must be trained.", "over_18_only": True},
        ]

        for v in venue_list:
            venue = VolunteerVenue.get_by_name(v['name'])
            if not venue:
                db.session.add(VolunteerVenue(**v))
            else:
                venue.mapref = v['mapref']

        for r in role_list:
            role = Role.get_by_name(r['name'])
            if not role:
                db.session.add(Role(**r))
            else:
                role.description = r['description']
                role.role_notes = r.get('role_notes', None)
                role.over_18_only = r.get('over_18_only', False)

        db.session.commit()


class MakeVolunteerShifts(Command):
    def run(self):
        # First = first start time. Final = end of last shift
        shift_list = {
            "Herald": {
                "Stage A": [
                    {"first": "2018-08-31 12:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                ],
                "Stage B": [
                    {"first": "2018-08-31 13:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                ],
                "Stage C": [
                    {"first": "2018-08-31 13:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                ],
            },
            "Stage: Audio/Visual": {
                "Stage A": [
                    {"first": "2018-08-31 12:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                ],
                "Stage B": [
                    {"first": "2018-08-31 13:00:00", "final": "2018-09-01 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-02 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 23:00:00", "min": 1, "max": 1},
                ],
                "Stage C": [
                    {"first": "2018-08-31 13:00:00", "final": "2018-09-01 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-02 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 23:00:00", "min": 1, "max": 1},
                ]
            },
            "Stage: Camera Operator": {
                "Stage A": [
                    {"first": "2018-08-31 12:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                ],
                "Stage B": [
                    {"first": "2018-08-31 13:00:00", "final": "2018-09-01 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-02 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 23:00:00", "min": 1, "max": 1},
                ],
                "Stage C": [
                    {"first": "2018-08-31 13:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                ]
            },
            "Stage: Vision Mixer": {
                "Stage A": [
                    {"first": "2018-08-31 12:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                ],
                "Stage B": [
                    {"first": "2018-08-31 13:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                ],
                "Stage C": [
                    {"first": "2018-08-31 13:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                ]
            },

            # 'Tent' roles
            "Badge Helper": {
                "Badge Tent": [
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 16:00:00", "min": 1, "max": 2},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 16:00:00", "min": 1, "max": 2},
                ]
            },
            "Car Parking": {
                "Car Park": [
                    {"first": "2018-08-31 08:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 3},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 16:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 14:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-03 08:00:00", "final": "2018-09-03 12:00:00", "min": 1, "max": 3},
                ]
            },
            "Entrance Steward": {
                "Entrance": [
                    {"first": "2018-08-31 08:00:00", "final": "2018-09-03 12:00:00", "min": 2, "max": 4},
                ]
            },
            "Games Master": {
                "Stage A": [
                    {"first": "2018-08-31 20:00:00", "final": "2018-08-31 23:00:00", "min": 1, "max": 3},
                    {"first": "2018-09-01 20:00:00", "final": "2018-09-01 23:00:00", "min": 1, "max": 3},
                    {"first": "2018-09-02 20:00:00", "final": "2018-09-02 23:00:00", "min": 1, "max": 3},
                ]
            },
            "Green Room": {
                "Green Room": [
                    {"first": "2018-08-31 12:00:00", "final": "2018-09-01 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-02 00:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                ]
            },
            "Info Desk": {
                "Info Desk": [
                    {"first": "2018-08-31 10:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 20:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 1},
                ]
            },
            "Tent Steward": {
                "N/A": [
                    {"first": "2018-08-31 13:00:00", "final": "2018-08-31 19:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 10:00:00", "final": "2018-09-01 19:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 10:00:00", "final": "2018-09-02 19:00:00", "min": 1, "max": 1},
                ]
            },
            "Youth Workshop Helper": {
                "Youth Workshop": [
                    {"first": "2018-08-31 13:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 2},
                    {"first": "2018-09-01 09:00:00", "final": "2018-09-01 20:00:00", "min": 1, "max": 2},
                    {"first": "2018-09-02 09:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 2},
                ]
            },

            # Require training
            "Bar": {
                "Bar": [
                    {"first": "2018-08-31 11:00:00", "final": "2018-09-01 02:00:00", "min": 2, "max": 5},
                    {"first": "2018-09-01 11:00:00", "final": "2018-09-02 02:00:00", "min": 2, "max": 5},
                    {"first": "2018-09-02 11:00:00", "final": "2018-09-03 01:00:00", "min": 2, "max": 5},
                ],
                "Bar 2": [
                    {"first": "2018-08-31 20:00:00", "final": "2018-09-01 01:00:00", "min": 1, "max": 2},
                    {"first": "2018-09-01 17:00:00", "final": "2018-09-02 01:00:00", "min": 1, "max": 2},
                    {"first": "2018-09-02 17:00:00", "final": "2018-09-03 00:00:00", "min": 1, "max": 2},
                ]
            },
            "NOC": {
                "N/A": [
                    {"first": "2018-08-31 08:00:00", "final": "2018-08-31 20:00:00", "min": 1, "max": 2},
                    {"first": "2018-09-02 14:00:00", "final": "2018-09-02 20:00:00", "min": 1, "max": 2},
                    {"first": "2018-09-03 08:00:00", "final": "2018-09-03 12:00:00", "min": 1, "max": 2},
                ]
            },
            "Volunteer Manager": {
                "Volunteer Tent": [
                    {"first": "2018-08-31 11:00:00", "final": "2018-08-31 21:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-01 09:00:00", "final": "2018-09-01 21:00:00", "min": 1, "max": 1},
                    {"first": "2018-09-02 09:00:00", "final": "2018-09-02 21:00:00", "min": 1, "max": 1},
                ]
            },
        }


        for shift_role in shift_list:
            role = Role.get_by_name(shift_role)

            if role.shifts:
                app.logger.info("Skipping making shifts for role: %s" % role.name)
                continue

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
