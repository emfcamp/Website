from datetime import timedelta

from flask import abort, redirect, url_for
from flask import current_app as app
from flask_login import current_user
from geoalchemy2.shape import to_shape
from pendulum import parse

from apps.common import render_markdown
from main import db
from models.cfp import WorkshopProposal
from models.volunteer import (
    Role,
    RoleAdmin,
    Shift,
    ShiftEntry,
    Volunteer,
    VolunteerVenue,
)

from ..common import feature_enabled, feature_flag
from . import v_admin_required, volunteer
from .init_data import load_initial_roles, load_initial_venues
from .shift_list import shift_list


@volunteer.route("/")
def main():
    if current_user.is_anonymous:
        return redirect(url_for(".info"))

    volunteer = Volunteer.get_for_user(current_user)
    if volunteer is None:
        return redirect(url_for(".info"))

    if feature_enabled("VOLUNTEERS_SCHEDULE") and volunteer.interested_roles.count() > 0:
        return redirect(url_for(".schedule"))

    return redirect(url_for(".choose_role"))


@volunteer.route("/info/<page_name>")
@feature_flag("VOLUNTEERS_SIGNUP")
def info_page(page_name: str):
    return render_markdown(f"volunteer/info/{page_name}", page_name=page_name)


@volunteer.route("/info")
@feature_flag("VOLUNTEERS_SIGNUP")
def info():
    return render_markdown("volunteer/info/index", page_name="index")


@volunteer.route("/init_shifts")
@v_admin_required
def init_shifts():
    for v in load_initial_venues():
        venue = VolunteerVenue.get_by_name(v["name"])
        if not venue:
            db.session.add(VolunteerVenue(**v))
        else:
            venue.mapref = v["mapref"]

    for r in load_initial_roles():
        role = Role.get_by_name(r["name"])
        if not role:
            db.session.add(Role(**r))
        else:
            role.description = r["description"]
            role.full_description = r.get("full_description", "")
            role.role_notes = r.get("role_notes", None)
            role.over_18_only = r.get("over_18_only", False)
            role.requires_training = r.get("requires_training", False)

    for shift_role in shift_list:
        role = Role.get_by_name(shift_role)
        if role is None:
            app.logger.error(f"Unknown role: {shift_role}")
            continue

        if role.shifts:
            app.logger.info(f"Skipping making shifts for role: {role.name}")
            continue

        for shift_venue in shift_list[shift_role]:
            venue = VolunteerVenue.get_by_name(shift_venue)
            if venue is None:
                app.logger.error(f"Unknown venue: {shift_venue}")
                continue

            for shift_range in shift_list[shift_role][shift_venue]:
                shifts = Shift.generate_for(
                    role=role,
                    venue=venue,
                    first=parse(shift_range["first"]),
                    final=parse(shift_range["final"]),
                    min=shift_range["min"],
                    max=shift_range["max"],
                    base_duration=shift_range.get("base_duration", 120),
                    changeover=shift_range.get("changeover", 15),
                )
                for s in shifts:
                    db.session.add(s)

    db.session.commit()
    return redirect(url_for(".main"))


@volunteer.route("/init_workshop_shifts")
@v_admin_required
def init_workshop_shifts():
    time_before_start = timedelta(minutes=30)
    time_after_start = timedelta(minutes=15)

    proposals = WorkshopProposal.query.filter_by(
        state="finalised", requires_ticket=True, user_scheduled=False, type="workshop"
    ).all()

    # Yes, I know. We shouldn't be tieing things to human readable role names. It's too
    # late to do anything about that right now.
    role = Role.query.filter_by(name="Workshop Steward").first()

    venues = {}
    with db.session.no_autoflush:
        for proposal in proposals:
            # This is terrible, and should be rewritten. If you're reading this it presumably hasn't been, and you
            # need to create some workshop shifts anyway, so here's what's happening.
            #
            # For each finalised workshop which requires tickets we want to create a volunteer shift for a workshop
            # steward. To go with those shifts we need a VolunteerVenue, which is a separate entity representing the
            # same physical location as the Venue associated with the proposal.
            #
            # Because multiple workshops may appear in the same venue we keep a dict of venue_name -> VolunteerVenue
            # instances to make sure we don't queue multiple instances of the same venue for insertion, which results
            # in a constraint violation, and makes the whole process throw a 500.
            #
            # If, as suspected, you're reading this in the future a week away from opening, I'm sorry, and share your
            # pain.
            if proposal.scheduled_venue.name in venues:
                venue = venues[proposal.scheduled_venue.name]
            else:
                venue = VolunteerVenue.query.filter_by(name=proposal.scheduled_venue.name).first()
                if venue is None:
                    location = to_shape(proposal.scheduled_venue.location)
                    mapref = f"https://map.emfcamp.org/#20.82/{location.y}/{location.x}"
                    venue = VolunteerVenue(name=proposal.scheduled_venue.name, mapref=mapref)
                    db.session.add(venue)
                venues[proposal.scheduled_venue.name] = venue

            shift = Shift.query.filter_by(proposal=proposal, role=role).first()
            if shift is None:
                shift = Shift(proposal=proposal, role=role, venue=venue)

            shift.start = proposal.scheduled_time - time_before_start
            shift.end = proposal.scheduled_time + time_after_start
            shift.min_needed = 1
            shift.max_needed = 1

            db.session.add(shift)
            db.session.commit()

    return redirect(url_for(".schedule"))


@volunteer.route("/clear_data")
@v_admin_required
def clear_data():
    if not app.config.get("DEBUG"):
        abort(404)
    for se in ShiftEntry.query.all():
        db.session.delete(se)
    for s in Shift.query.all():
        db.session.delete(s)
    for ra in RoleAdmin.query.all():
        db.session.delete(ra)
    for r in Role.query.all():
        db.session.delete(r)
    for v in VolunteerVenue.query.all():
        db.session.delete(v)
    db.session.commit()
    return redirect(url_for(".main"))
