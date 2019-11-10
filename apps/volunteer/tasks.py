""" Volunteer system CLI tasks """
from pendulum import instance
from flask import current_app as app

from main import db

from models.cfp import Proposal, Venue
from models.volunteer.role import Role
from models.volunteer.shift import Shift
from models.volunteer.venue import VolunteerVenue

from . import volunteer


def get_end_time(proposal):
    return instance(proposal.scheduled_time).add(minutes=proposal.scheduled_duration)


def get_start_time(proposal):
    return instance(proposal.scheduled_time).add(minutes=-15)


@volunteer.cli.command("make_shifts")
def run(self):
    roles_list = [
        "Herald",
        "Stage: Audio/Visual",
        "Stage: Camera Operator",
        "Stage: Vision Mixer",
    ]

    venue_list = ["Stage A", "Stage B", "Stage C"]

    for role_name in roles_list:
        role = Role.get_by_name(role_name)

        if role.shifts:
            for shift in role.shifts:
                p = shift.proposal
                app.logger.info("Updating shift")
                shift.start = get_start_time(p)
                shift.stop = get_end_time(p)
                shift.venue = VolunteerVenue.get_by_name(p.scheduled_venue.name)
        else:
            for venue_name in venue_list:
                venue = VolunteerVenue.get_by_name(venue_name)

                events = (
                    Proposal.query.join(Venue, Proposal.scheduled_venue_id == Venue.id)
                    .filter(Venue.name == venue.name, Proposal.state == "finished")
                    .all()
                )
                for e in events:
                    start = get_start_time(e)
                    stop = get_end_time(e)
                    to_add = Shift(
                        role=role,
                        venue=venue,
                        start=start,
                        end=stop,
                        min_needed=1,
                        max_needed=1,
                        proposal=e,
                    )
                    db.session.add(to_add)
    db.session.commit()
