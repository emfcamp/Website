from datetime import timedelta

from flask import abort, redirect, url_for
from flask import current_app as app
from flask.typing import ResponseReturnValue
from flask_login import current_user
from geoalchemy2.shape import to_shape
from sqlalchemy import select

from apps.common import render_template_markdown
from main import db
from models.content import Occurrence, ScheduleItem
from models.volunteer import (
    Role,
    Shift,
    ShiftEntry,
    Volunteer,
    VolunteerVenue,
)

from ..common import feature_enabled, feature_flag
from . import init_data, v_admin_required, volunteer


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
def info_page(page_name: str) -> ResponseReturnValue:
    return render_template_markdown(f"volunteer/info/{page_name}.md", page_name=page_name)


@volunteer.route("/info")
def info():
    if not feature_enabled("VOLUNTEERS_SIGNUP"):
        # Rather than 404ing, point at the misc 'volunteering' page instead.
        return redirect(url_for("base.page", page_name="volunteering"))
    return render_template_markdown("volunteer/info/index.md", page_name="index")


@volunteer.route("/init-shifts")
@v_admin_required
def init_shifts():
    init_data.shifts()
    return redirect(url_for(".main"))


@volunteer.route("/init-workshop-shifts")
@v_admin_required
def init_workshop_shifts():
    time_before_start = timedelta(minutes=30)
    time_after_start = timedelta(minutes=15)

    schedule_items = list(
        db.session.scalars(
            select(ScheduleItem)
            .where(ScheduleItem.type == "workshop")
            .where(ScheduleItem.state == "published")
            .where(ScheduleItem.official_content == True)
            .where(ScheduleItem.occurrences.any(Occurrence.has(Occurrence.lottery)))
        )
    )

    workshop_steward_role = Role.query.filter_by(slug="workshop-ticket-inspector").one()

    venues = {}
    with db.session.no_autoflush:
        for schedule_item in schedule_items:
            for occurrence in schedule_item.occurrences:
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
                if occurrence.scheduled_venue.name in venues:
                    venue = venues[occurrence.scheduled_venue.name]
                else:
                    venue = VolunteerVenue.query.filter_by(name=occurrence.scheduled_venue.name).first()
                    if venue is None:
                        location = to_shape(occurrence.scheduled_venue.location)
                        mapref = f"https://map.emfcamp.org/#20.82/{location.y}/{location.x}"
                        venue = VolunteerVenue(name=occurrence.scheduled_venue.name, mapref=mapref)
                        db.session.add(venue)
                    venues[occurrence.scheduled_venue.name] = venue

                shift = Shift.query.filter_by(occurrence=occurrence, role=workshop_steward_role).first()
                if shift is None:
                    shift = Shift(occurrence=occurrence, role=workshop_steward_role, venue=venue)

                shift.start = occurrence.scheduled_time - time_before_start
                shift.end = occurrence.scheduled_time + time_after_start
                shift.min_needed = 1
                shift.max_needed = 1

                db.session.add(shift)
                db.session.commit()

    return redirect(url_for(".schedule"))


@volunteer.route("/clear-data")
@v_admin_required
def clear_data():
    if not app.config.get("DEBUG"):
        abort(404)
    for se in ShiftEntry.query.all():
        db.session.delete(se)
    for s in Shift.query.all():
        db.session.delete(s)
    for r in Role.query.all():
        db.session.delete(r)
    for v in VolunteerVenue.query.all():
        db.session.delete(v)
    db.session.commit()
    return redirect(url_for(".main"))
