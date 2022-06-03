# encoding=utf-8
from flask import redirect, url_for, render_template, current_app as app, abort
from flask_login import current_user
from pendulum import parse

from . import volunteer, v_admin_required
from ..common import feature_flag

from main import db
from models.volunteer import (
    Volunteer,
    VolunteerVenue,
    Role,
    RoleAdmin,
    Shift,
    ShiftEntry,
)
from .init_data import venue_list, role_list, shift_list


@volunteer.route("/")
@feature_flag("VOLUNTEERS_SIGNUP")
def main():
    if current_user.is_authenticated and Volunteer.get_for_user(current_user):
        return redirect(url_for(".schedule"))
    return redirect(url_for(".sign_up"))


@volunteer.route("/safeguarding")
@feature_flag("VOLUNTEERS_SIGNUP")
def safeguarding():
    return render_template("volunteer/safeguarding.html")


@volunteer.route("/info")
@feature_flag("VOLUNTEERS_SIGNUP")
def info():
    return render_template("volunteer/info.html")


@volunteer.route("/info/emergency")
@feature_flag("VOLUNTEERS_SIGNUP")
def info_emergency():
    return render_template("volunteer/info_emergency.html")


@volunteer.route("/info/lost_child")
@feature_flag("VOLUNTEERS_SIGNUP")
def info_lost_child():
    return render_template("volunteer/info_lost_child.html")


@volunteer.route("/info/food")
@feature_flag("VOLUNTEERS_SIGNUP")
def info_food():
    return render_template("volunteer/info_food.html")


@volunteer.route("/init_shifts")
@v_admin_required
def init_shifts():
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
            app.logger.info("Skipping making shifts for role: %s" % role.name)
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
