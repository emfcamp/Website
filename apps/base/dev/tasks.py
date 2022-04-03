""" Development CLI tasks """
import click
from pendulum import parse
from flask import current_app as app

from main import db

from models.volunteer.venue import VolunteerVenue
from models.volunteer.shift import Shift
from models.volunteer.role import Role

from . import dev_cli
from .fake import FakeDataGenerator


@dev_cli.command("data")
@click.pass_context
def dev_data(ctx):
    """Make all categories of fake data for dev"""
    ctx.invoke(fake_data)
    ctx.invoke(volunteer_data)
    ctx.invoke(volunteer_shifts)


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
    shift_list = {
        # 'Tent' roles
        "Badge Helper": {
            "Badge Tent": [
                {
                    "first": "2022-06-04 10:00:00",
                    "final": "2022-06-04 16:00:00",
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": "2022-06-05 10:00:00",
                    "final": "2022-06-05 16:00:00",
                    "min": 1,
                    "max": 2,
                },
            ]
        },
        "Car Parking": {
            "Car Park": [
                {
                    "first": "2022-06-02 08:00:00",
                    "final": "2022-06-02 20:00:00",
                    "min": 1,
                    "max": 3,
                },
                {
                    "first": "2022-06-03 08:00:00",
                    "final": "2022-06-03 20:00:00",
                    "min": 1,
                    "max": 3,
                },
                {
                    "first": "2022-06-04 10:00:00",
                    "final": "2022-06-04 16:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-05 14:00:00",
                    "final": "2022-06-05 20:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-06 08:00:00",
                    "final": "2022-06-06 12:00:00",
                    "min": 1,
                    "max": 3,
                },
            ]
        },
        "Catering": {
            "Volunteer Tent": [
                {
                    "first": "2022-06-02 07:00:00",
                    "final": "2022-06-02 20:00:00",
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": "2022-06-03 07:00:00",
                    "final": "2022-06-03 20:00:00",
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": "2022-06-04 07:00:00",
                    "final": "2022-06-04 20:00:00",
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": "2022-06-05 07:00:00",
                    "final": "2022-06-05 20:00:00",
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": "2022-06-06 07:00:00",
                    "final": "2022-06-06 20:00:00",
                    "min": 2,
                    "max": 5,
                },
            ]
        },
        "Entrance Steward": {
            "Entrance": [
                {
                    "first": "2022-06-02 08:00:00",
                    "final": "2022-06-06 12:00:00",
                    "min": 2,
                    "max": 4,
                }
            ]
        },
        "Games Master": {
            "Stage A": [
                {
                    "first": "2022-06-02 20:00:00",
                    "final": "2022-06-02 23:00:00",
                    "min": 1,
                    "max": 3,
                },
                {
                    "first": "2022-06-03 20:00:00",
                    "final": "2022-06-03 23:00:00",
                    "min": 1,
                    "max": 3,
                },
                {
                    "first": "2022-06-04 20:00:00",
                    "final": "2022-06-04 23:00:00",
                    "min": 1,
                    "max": 3,
                },
                {
                    "first": "2022-06-05 20:00:00",
                    "final": "2022-06-05 23:00:00",
                    "min": 1,
                    "max": 3,
                },
            ]
        },
        "Green Room": {
            "Green Room": [
                {
                    "first": "2022-06-03 12:00:00",
                    "final": "2022-06-04 00:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-04 10:00:00",
                    "final": "2022-06-05 00:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-05 10:00:00",
                    "final": "2022-06-05 20:00:00",
                    "min": 1,
                    "max": 1,
                },
            ]
        },
        "Info Desk": {
            "Info Desk": [
                {
                    "first": "2022-06-02 10:00:00",
                    "final": "2022-06-02 20:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-03 10:00:00",
                    "final": "2022-06-03 20:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-03 10:00:00",
                    "final": "2022-06-03 20:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-04 10:00:00",
                    "final": "2022-06-04 20:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-05 10:00:00",
                    "final": "2022-06-05 20:00:00",
                    "min": 1,
                    "max": 1,
                },
            ]
        },
        "Tent Steward": {
            "N/A": [
                {
                    "first": "2022-06-02 13:00:00",
                    "final": "2022-06-02 19:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-03 13:00:00",
                    "final": "2022-06-03 19:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-04 10:00:00",
                    "final": "2022-06-04 19:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-05 10:00:00",
                    "final": "2022-06-05 19:00:00",
                    "min": 1,
                    "max": 1,
                },
            ]
        },
        "Youth Workshop Helper": {
            "Youth Workshop": [
                {
                    "first": "2022-06-02 13:00:00",
                    "final": "2022-06-02 20:00:00",
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": "2022-06-03 13:00:00",
                    "final": "2022-06-03 20:00:00",
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": "2022-06-04 09:00:00",
                    "final": "2022-06-04 20:00:00",
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": "2022-06-05 09:00:00",
                    "final": "2022-06-05 20:00:00",
                    "min": 1,
                    "max": 2,
                },
            ]
        },
        # Require training
        "Bar": {
            "Bar": [
                {
                    "first": "2022-06-02 11:00:00",
                    "final": "2022-06-03 02:00:00",
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": "2022-06-03 11:00:00",
                    "final": "2022-06-04 02:00:00",
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": "2022-06-04 11:00:00",
                    "final": "2022-06-05 02:00:00",
                    "min": 2,
                    "max": 5,
                },
                {
                    "first": "2022-06-05 11:00:00",
                    "final": "2022-06-06 01:00:00",
                    "min": 2,
                    "max": 5,
                },
            ],
            "Bar 2": [
                {
                    "first": "2022-06-03 20:00:00",
                    "final": "2022-06-04 01:00:00",
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": "2022-06-04 17:00:00",
                    "final": "2022-06-05 01:00:00",
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": "2022-06-05 17:00:00",
                    "final": "2022-06-06 00:00:00",
                    "min": 1,
                    "max": 2,
                },
            ],
        },
        "NOC": {
            "N/A": [
                {
                    "first": "2022-06-02 08:00:00",
                    "final": "2022-06-02 20:00:00",
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": "2022-06-03 08:00:00",
                    "final": "2022-06-03 20:00:00",
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": "2022-06-05 14:00:00",
                    "final": "2022-06-05 20:00:00",
                    "min": 1,
                    "max": 2,
                },
                {
                    "first": "2022-06-06 08:00:00",
                    "final": "2022-06-06 12:00:00",
                    "min": 1,
                    "max": 2,
                },
            ]
        },
        "Volunteer Manager": {
            "Volunteer Tent": [
                {
                    "first": "2022-06-02 11:00:00",
                    "final": "2022-06-02 21:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-03 11:00:00",
                    "final": "2022-06-03 21:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-04 09:00:00",
                    "final": "2022-06-04 21:00:00",
                    "min": 1,
                    "max": 1,
                },
                {
                    "first": "2022-06-05 09:00:00",
                    "final": "2022-06-05 21:00:00",
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
                    first=parse(shift_ranges["first"]),
                    final=parse(shift_ranges["final"]),
                    min=shift_ranges["min"],
                    max=shift_ranges["max"],
                )
                for s in shifts:
                    db.session.add(s)

    db.session.commit()
