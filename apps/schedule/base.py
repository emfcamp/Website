import html
import random
import pendulum
from collections import defaultdict

from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from flask import current_app as app

from main import db
from models import event_year
from models.cfp import Proposal
from models.ical import CalendarSource, CalendarEvent
from models.user import generate_api_token
from models.admin_message import AdminMessage

from ..common import feature_flag, feature_enabled

from . import schedule, event_tz
from .historic import talks_historic, item_historic, historic_talk_data
from .data import _get_upcoming


@schedule.route("/schedule/")
def main():
    return redirect(url_for(".main_year", year=event_year()))


@schedule.route("/schedule/<int:year>")
def main_year(year):
    # Do we want to show the current year's schedule from the DB,
    # or a previous year's from the static archive?
    if year == event_year():
        if feature_enabled("SCHEDULE"):
            # Schedule is ready, show it
            return schedule_current()
        elif feature_enabled("LINE_UP"):
            # Show the lineup (list of talks without times/venues)
            return line_up()
        else:
            # No schedule should be shown yet.
            return render_template("schedule/no-schedule.html")
    else:
        return talks_historic(year)


def schedule_current():
    token = None
    if current_user.is_authenticated:
        token = generate_api_token(app.config["SECRET_KEY"], current_user.id)

    return render_template(
        "schedule/user_schedule.html",
        token=token,
        debug=app.config.get("DEBUG"),
        year=event_year(),
    )


def line_up():
    proposals = Proposal.query.filter(
        Proposal.scheduled_duration.isnot(None),
        Proposal.state.in_(["accepted", "finished"]),
        Proposal.type.in_(["talk", "workshop", "youthworkshop", "performance"]),
        Proposal.hide_from_schedule.isnot(True),
    ).all()

    # Shuffle the order, but keep it fixed per-user
    # (Because we don't want a bias in starring)
    random.Random(current_user.get_id()).shuffle(proposals)

    externals = CalendarSource.get_enabled_events()

    return render_template(
        "schedule/line-up.html", proposals=proposals, externals=externals
    )


@schedule.route("/schedule/add_favourite", methods=["POST"])
def add_favourite():
    if not current_user.is_authenticated:
        abort(401)

    event_id = int(request.form["fave"])
    event_type = request.form["event_type"]
    if event_type == "proposal":
        proposal = Proposal.query.get_or_404(event_id)
        if proposal in current_user.favourites:
            current_user.favourites.remove(proposal)
        else:
            current_user.favourites.append(proposal)

        db.session.commit()
        return redirect(
            url_for(".main_year", year=event_year())
            + "#proposal-{}".format(proposal.id)
        )

    else:
        event = CalendarEvent.query.get_or_404(event_id)
        if event in current_user.calendar_favourites:
            current_user.calendar_favourites.remove(event)
        else:
            current_user.calendar_favourites.append(event)

        db.session.commit()
        return redirect(
            url_for(".main_year", year=event_year()) + "#event-{}".format(event.id)
        )


@schedule.route("/favourites", methods=["GET", "POST"])
@feature_flag("LINE_UP")
def favourites():
    if (request.method == "POST") and current_user.is_authenticated:
        event_id = int(request.form["fave"])
        event_type = request.form["event_type"]
        if event_type == "proposal":
            proposal = Proposal.query.get_or_404(event_id)
            if proposal in current_user.favourites:
                current_user.favourites.remove(proposal)
            else:
                current_user.favourites.append(proposal)

            db.session.commit()
            return redirect(url_for(".favourites") + "#proposal-{}".format(proposal.id))

        else:
            event = CalendarEvent.query.get_or_404(event_id)
            if event in current_user.calendar_favourites:
                current_user.calendar_favourites.remove(event)
            else:
                current_user.calendar_favourites.append(event)

            db.session.commit()
            return redirect(url_for(".favourites") + "#event-{}".format(event.id))

    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".favourites")))

    proposals = current_user.favourites
    externals = current_user.calendar_favourites

    token = generate_api_token(app.config["SECRET_KEY"], current_user.id)

    return render_template(
        "schedule/favourites.html",
        proposals=proposals,
        externals=externals,
        token=token,
    )


@schedule.route("/schedule/<int:year>/<int:proposal_id>", methods=["GET", "POST"])
@schedule.route(
    "/schedule/<int:year>/<int:proposal_id>-<slug>", methods=["GET", "POST"]
)
def item(year, proposal_id, slug=None):
    """Display a detail page for a schedule item"""
    if year == event_year():
        return item_current(year, proposal_id, slug)
    else:
        return item_historic(year, proposal_id, slug)


def item_current(year, proposal_id, slug=None):
    """Display a detail page for a talk from the current event"""
    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.state not in ("accepted", "finished") or proposal.hide_from_schedule:
        abort(404)

    if not current_user.is_anonymous:
        is_fave = proposal in current_user.favourites
    else:
        is_fave = False

    if (request.method == "POST") and not current_user.is_anonymous:
        if is_fave:
            current_user.favourites.remove(proposal)
            msg = 'Removed "%s" from favourites' % proposal.display_title
        else:
            current_user.favourites.append(proposal)
            msg = 'Added "%s" to favourites' % proposal.display_title
        db.session.commit()
        flash(msg)
        return redirect(
            url_for(".item", year=year, proposal_id=proposal.id, slug=proposal.slug)
        )

    if slug != proposal.slug:
        return redirect(
            url_for(".item", year=year, proposal_id=proposal.id, slug=proposal.slug)
        )

    venue_name = None
    if proposal.scheduled_venue:
        venue_name = proposal.scheduled_venue.name

    return render_template(
        "schedule/item.html", proposal=proposal, is_fave=is_fave, venue_name=venue_name
    )


@schedule.route("/now-and-next")
def now_and_next():
    proposals = _get_upcoming(request.args)
    arg_venues = request.args.getlist("venue", type=str)
    venues = [html.escape(v) for v in arg_venues]

    admin_messages = AdminMessage.get_visible_messages()

    for msg in admin_messages:
        flash(msg.message)

    if request.args.get("fullscreen", default=False, type=bool):
        template = "schedule/now-and-next-fullscreen.html"
    else:
        template = "schedule/now-and-next.html"

    return render_template(template, venues=venues, proposals_by_venue=proposals)


@schedule.route("/time-machine")
def time_machine():
    # now = pendulum.datetime(2018, 8, 31, 12, 00, tz=event_tz)
    now = pendulum.now(event_tz)
    now_time = now.time()
    now_weekday = now.weekday()

    days = [4, 5, 6]  # Friday  # Saturday  # Sunday

    years = [2012, 2014, 2016, 2018, 2022]

    # Year -> Stage -> Talks
    talks_now = defaultdict(lambda: defaultdict(list))
    talks_next = defaultdict(lambda: defaultdict(list))

    for year in years:
        talks = None
        for venues in historic_talk_data(year)["venues"]:
            if venues["name"] == "Main Stages":
                talks = venues["events"]
                break

        filtered_talks = [
            t
            for t in talks
            if t["end_date"].weekday() == now_weekday
            and t["end_date"].time() >= now_time
        ]

        for talk in sorted(filtered_talks, key=lambda v: v["start_date"]):
            if talk["start_date"].time() <= now_time:
                talks_now[year][talk["venue"]].append(talk)
            else:
                talk["starts_in"] = talk["start_date"].time() - now_time
                talks_next[year][talk["venue"]].append(talk)

    return render_template(
        "schedule/time-machine.html",
        talks_now=talks_now,
        talks_next=talks_next,
        now=now,
    )
