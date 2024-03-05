""" Development CLI tasks """
import click
from pendulum import Duration as Offset, parse
from flask import current_app as app
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from main import db

from models.volunteer.venue import VolunteerVenue
from models.volunteer.shift import Shift
from models.volunteer.role import Role

from apps.cfp.tasks import create_tags
from models.payment import BankAccount

from . import dev_cli
from .fake import FakeDataGenerator


@dev_cli.command("data")
@click.pass_context
def dev_data(ctx):
    """Make all categories of fake data for dev"""
    ctx.invoke(fake_data)
    ctx.invoke(volunteer_data)
    ctx.invoke(volunteer_shifts)
    ctx.invoke(create_tags)
    ctx.invoke(create_bank_accounts)


@dev_cli.command("cfp_data")
def fake_data():
    """Make fake users, proposals, locations, etc"""
    fdg = FakeDataGenerator()
    fdg.run()


@dev_cli.command("volunteer_data")
def volunteer_data():
    """Make fake volunteer system data"""
    venue_list = [
        {
            "name": "Badge Tent",
            "mapref": "https://map.emfcamp.org/#20.24/52.0405486/-2.3781891",
        },
        {
            "name": "Bar 2",
            "mapref": "https://map.emfcamp.org/#19/52.0409755/-2.3786306",
        },
        {"name": "Bar", "mapref": "https://map.emfcamp.org/#19/52.0420157/-2.3770749"},
        {
            "name": "Car Park",
            "mapref": "https://map.emfcamp.org/#19.19/52.0389412/-2.3783488",
        },
        {
            "name": "Entrance",
            "mapref": "https://map.emfcamp.org/#18/52.039226/-2.378184",
        },
        {
            "name": "Green Room",
            "mapref": "https://map.emfcamp.org/#20.72/52.0414959/-2.378016",
        },
        {
            "name": "Info Desk",
            "mapref": "https://map.emfcamp.org/#21.49/52.0415113/-2.3776567",
        },
        {
            "name": "Stage A",
            "mapref": "https://map.emfcamp.org/#17/52.039601/-2.377759",
        },
        {
            "name": "Stage B",
            "mapref": "https://map.emfcamp.org/#17/52.041798/-2.376412",
        },
        {
            "name": "Stage C",
            "mapref": "https://map.emfcamp.org/#17/52.040482/-2.377432",
        },
        {
            "name": "Volunteer Tent",
            "mapref": "https://map.emfcamp.org/#20.82/52.0397817/-2.3767928",
        },
        {
            "name": "Youth Workshop",
            "mapref": "https://map.emfcamp.org/#19.46/52.0420979/-2.3753702",
        },
        {"name": "N/A", "mapref": "https://map.emfcamp.org/#16/52.0411/-2.3784"},
    ]
    # DO not change these names (each keys a description in apps/volunteer/role_descriptions/)
    role_list = [
        # Stage stuff
        {
            "name": "Herald",
            "description": "Introduce talks and manage speakers at stage.",
        },
        {
            "name": "Stage: Audio/Visual",
            "description": "Run the audio for a stage. Make sure mics are working and that presentations work.",
        },
        {
            "name": "Stage: Camera Operator",
            "description": "Point, focus and expose the camera, then lock off shot and monitor it.",
        },
        {
            "name": "Stage: Vision Mixer",
            "description": "Vision mix the output to screen and to stream.",
        },
        # "Tent" roles
        {
            "name": "Badge Helper",
            "description": "Fix, replace and troubleshoot badges and their software.",
        },
        {
            "name": "Car Parking",
            "description": "Help park cars and get people on/off site.",
        },
        {
            "name": "Catering",
            "description": "Help our excellent catering team provide food for all the volunteers.",
        },
        {
            "name": "Entrance Steward",
            "description": "Greet people, check their tickets and help them get on site.",
        },
        {
            "name": "Games Master",
            "description": "Running Indie Games on the big screen in Stage A, and optionally Board Games.",
        },
        {
            "name": "Green Room",
            "description": "Make sure speakers get where they need to be with what they need.",
        },
        {
            "name": "Info Desk",
            "description": "Be a point of contact for attendees. Either helping with finding things or just getting an idea for what's on.",
        },
        {
            "name": "Tent Steward",
            "description": "Check the various tents (e.g. Arcade, Lounge, Spillout) are clean and everything's OK.",
        },
        {
            "name": "Youth Workshop Helper",
            "description": "Help support our youth workshop leaders and participants.",
        },
        # Needs training
        {
            "name": "NOC",
            "description": "Plug/Unplug DKs",
            "role_notes": "Requires training & the DK Key.",
            "requires_training": True,
        },
        {
            "name": "Bar",
            "description": "Help run the bar. Serve drinks, take payment, keep it clean.",
            "role_notes": "Requires training, over 18s only.",
            "over_18_only": True,
            "requires_training": True,
        },
        {
            "name": "Volunteer Manager",
            "description": "Help people sign up for volunteering. Make sure they know where to go. Run admin on the volunteer system.",
            "role_notes": "Must be trained.",
            "over_18_only": True,
            "requires_training": True,
        },
    ]

    for v in venue_list:
        venue = VolunteerVenue.get_by_name(v["name"])
        if not venue:
            db.session.add(VolunteerVenue(**v))
        else:
            venue.mapref = v["mapref"]

    for r in role_list:
        role = Role.get_by_name(r["name"])
        if not role:
            db.session.add(Role(**r))
        else:
            role.description = r["description"]
            role.role_notes = r.get("role_notes", None)
            role.over_18_only = r.get("over_18_only", False)
            role.requires_training = r.get("requires_training", False)

    db.session.commit()


@dev_cli.command("volunteer_shifts")
def volunteer_shifts():
    """Make fake volunteer shifts"""
    # First = first start time. Final = end of last shift
    start_date = parse(app.config["EVENT_START"]).set(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    shift_list = {
        # 'Tent' roles
        "Badge Helper": {
            "Badge Tent": [
                {
                    "first": Offset(days=2, hours=10),
                    "final": Offset(days=2, hours=16),
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": Offset(days=3, hours=10),
                    "final": Offset(days=3, hours=16),
                    "min": 1,
                    "max": 2,
                },
            ]
        },
        "Car Parking": {
            "Car Park": [
                {
                    "first": Offset(hours=8),
                    "final": Offset(hours=20),
                    "min": 1,
                    "max": 3,
                },
                {
                    "first": Offset(days=1, hours=8),
                    "final": Offset(days=1, hours=20),
                    "min": 1,
                    "max": 3,
                },
                {
                    "first": Offset(days=2, hours=10),
                    "final": Offset(days=2, hours=16),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=3, hours=14),
                    "final": Offset(days=3, hours=20),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=4, hours=8),
                    "final": Offset(days=4, hours=12),
                    "min": 1,
                    "max": 3,
                },
            ]
        },
        "Catering": {
            "Volunteer Tent": [
                {
                    "first": Offset(hours=7),
                    "final": Offset(hours=20),
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": Offset(days=1, hours=7),
                    "final": Offset(days=1, hours=20),
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": Offset(days=2, hours=7),
                    "final": Offset(days=2, hours=20),
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": Offset(days=3, hours=7),
                    "final": Offset(days=3, hours=20),
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": Offset(days=4, hours=7),
                    "final": Offset(days=4, hours=20),
                    "min": 2,
                    "max": 5,
                },
            ]
        },
        "Entrance Steward": {
            "Entrance": [
                {
                    "first": Offset(hours=8),
                    "final": Offset(days=4, hours=12),
                    "min": 2,
                    "max": 4,
                }
            ]
        },
        "Games Master": {
            "Stage A": [
                {
                    "first": Offset(hours=20),
                    "final": Offset(hours=23),
                    "min": 1,
                    "max": 3,
                },
                {
                    "first": Offset(days=1, hours=20),
                    "final": Offset(days=1, hours=23),
                    "min": 1,
                    "max": 3,
                },
                {
                    "first": Offset(days=2, hours=20),
                    "final": Offset(days=2, hours=23),
                    "min": 1,
                    "max": 3,
                },
                {
                    "first": Offset(days=3, hours=20),
                    "final": Offset(days=3, hours=23),
                    "min": 1,
                    "max": 3,
                },
            ]
        },
        "Green Room": {
            "Green Room": [
                {
                    "first": Offset(days=1, hours=12),
                    "final": Offset(days=2, hours=0),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=2, hours=10),
                    "final": Offset(days=3, hours=0),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=3, hours=10),
                    "final": Offset(days=3, hours=20),
                    "min": 1,
                    "max": 1,
                },
            ]
        },
        "Info Desk": {
            "Info Desk": [
                {
                    "first": Offset(hours=10),
                    "final": Offset(hours=20),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=1, hours=10),
                    "final": Offset(days=1, hours=20),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=1, hours=10),
                    "final": Offset(days=1, hours=20),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=2, hours=10),
                    "final": Offset(days=2, hours=20),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=3, hours=10),
                    "final": Offset(days=3, hours=20),
                    "min": 1,
                    "max": 1,
                },
            ]
        },
        "Tent Steward": {
            "N/A": [
                {
                    "first": Offset(hours=13),
                    "final": Offset(hours=19),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=1, hours=13),
                    "final": Offset(days=1, hours=19),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=2, hours=10),
                    "final": Offset(days=2, hours=19),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=3, hours=10),
                    "final": Offset(days=3, hours=19),
                    "min": 1,
                    "max": 1,
                },
            ]
        },
        "Youth Workshop Helper": {
            "Youth Workshop": [
                {
                    "first": Offset(hours=13),
                    "final": Offset(hours=20),
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": Offset(days=1, hours=13),
                    "final": Offset(days=1, hours=20),
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": Offset(days=2, hours=9),
                    "final": Offset(days=2, hours=20),
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": Offset(days=3, hours=9),
                    "final": Offset(days=3, hours=20),
                    "min": 1,
                    "max": 2,
                },
            ]
        },
        # Require training
        "Bar": {
            "Bar": [
                {
                    "first": Offset(hours=11),
                    "final": Offset(days=1, hours=2),
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": Offset(days=1, hours=11),
                    "final": Offset(days=2, hours=2),
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": Offset(days=2, hours=11),
                    "final": Offset(days=3, hours=2),
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": Offset(days=3, hours=11),
                    "final": Offset(days=4, hours=1),
                    "min": 2,
                    "max": 5,
                },
            ],
            "Bar 2": [
                {
                    "first": Offset(days=1, hours=20),
                    "final": Offset(days=2, hours=1),
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": Offset(days=2, hours=17),
                    "final": Offset(days=3, hours=1),
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": Offset(days=3, hours=17),
                    "final": Offset(days=4, hours=0),
                    "min": 1,
                    "max": 2,
                },
            ],
        },
        "NOC": {
            "N/A": [
                {
                    "first": Offset(hours=8),
                    "final": Offset(hours=20),
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": Offset(days=1, hours=8),
                    "final": Offset(days=1, hours=20),
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": Offset(days=3, hours=14),
                    "final": Offset(days=3, hours=20),
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": Offset(days=4, hours=8),
                    "final": Offset(days=4, hours=12),
                    "min": 1,
                    "max": 2,
                },
            ]
        },
        "Volunteer Manager": {
            "Volunteer Tent": [
                {
                    "first": Offset(hours=11),
                    "final": Offset(hours=21),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=1, hours=11),
                    "final": Offset(days=1, hours=21),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=2, hours=9),
                    "final": Offset(days=2, hours=21),
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": Offset(days=3, hours=9),
                    "final": Offset(days=3, hours=21),
                    "min": 1,
                    "max": 1,
                },
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
                shifts = Shift.generate_for(
                    role=role,
                    venue=venue,
                    first=start_date + shift_ranges["first"],
                    final=start_date + shift_ranges["final"],
                    min=shift_ranges["min"],
                    max=shift_ranges["max"],
                    changeover=0,
                )
                for s in shifts:
                    db.session.add(s)

    db.session.commit()


@dev_cli.command("createbankaccounts")
def create_bank_accounts_cmd():
    create_bank_accounts()


def create_bank_accounts():
    """Create bank accounts if they don't exist"""
    gbp = BankAccount(
        sort_code="102030",
        acct_id="40506070",
        currency="GBP",
        active=True,
        payee_name="EMF Festivals Ltd",
        institution="London Bank",
        address="13 Bartlett Place, London, WC1B 4NM",
        iban=None,
        swift=None,
    )
    eur = BankAccount(
        sort_code=None,
        acct_id=None,
        currency="EUR",
        active=True,
        payee_name="EMF Festivals Ltd",
        institution="London Bank",
        address="13 Bartlett Place, London, WC1B 4NM",
        iban="GB33BUKB20201555555555",
        swift="BUKBGB33",
    )
    for acct in [gbp, eur]:
        try:
            BankAccount.query.filter_by(
                acct_id=acct.acct_id, sort_code=acct.sort_code
            ).one()
        except NoResultFound:
            app.logger.info(
                "Adding %s account %s %s",
                acct.currency,
                acct.sort_code or acct.swift,
                acct.acct_id or acct.iban,
            )
            db.session.add(acct)
        except MultipleResultsFound:
            pass

    db.session.commit()
