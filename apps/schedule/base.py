import html
import random
import pendulum
from datetime import datetime, timedelta
from collections import defaultdict

from flask import render_template, redirect, url_for, flash, request, abort
from flask_login import current_user
from flask import current_app as app

from wtforms import BooleanField, SubmitField, FormField, StringField, SelectField

from main import db
from models import event_year
from models.cfp import Proposal, Venue
from models.ical import CalendarSource, CalendarEvent
from models.user import generate_api_token
from models.admin_message import AdminMessage
from models.site_state import get_signup_state
from models.event_tickets import create_ticket, create_lottery_ticket

from ..common import feature_flag, feature_enabled
from ..common.forms import Form
from ..common.fields import HiddenIntegerField
from ..volunteer import v_user_required
from ..cfp_review import admin_required as cfp_admin_required

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
        Proposal.is_accepted,
        # FIXME this should be all types. Proposal.type.in_(["talk", "workshop", "youthworkshop", "performance"]),
        Proposal.type.in_(["talk", "workshop", "youthworkshop"]),
        Proposal.user_scheduled.isnot(True),
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

    proposals = [p for p in current_user.favourites if not p.hide_from_schedule]
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


class ItemForm(Form):
    toggle_favourite = SubmitField("Favourite")
    # Signup/eventticket bits
    get_ticket = SubmitField("Get Ticket")
    enter_lottery = SubmitField("Enter lottery")


def item_current(year, proposal_id, slug=None):
    """Display a detail page for a talk from the current event"""
    proposal = Proposal.query.get_or_404(proposal_id)
    if not proposal.is_accepted or proposal.hide_from_schedule:
        abort(404)

    if not current_user.is_anonymous:
        is_fave = proposal in current_user.favourites
    else:
        is_fave = False

    form = ItemForm()

    if form.validate_on_submit() and not current_user.is_anonymous:
        msg = ""
        if form.toggle_favourite.data:
            if is_fave:
                current_user.favourites.remove(proposal)
                msg = f'Removed "{proposal.display_title}" from favourites'
            else:
                current_user.favourites.append(proposal)
                msg = f'Added "{proposal.display_title}" to favourites'

        elif (
            form.get_ticket.data and current_user.has_ticket_for_event(proposal.id)
        ) or (
            form.enter_lottery.data
            and current_user.has_lottery_ticket_for_event(proposal.id)
        ):
            msg = f"You already have a ticket for this event"
        elif (
            form.get_ticket.data
            and get_signup_state() == "issue_tickets"
            and proposal.has_ticket_capacity
        ):
            msg = f'Signed up for "{proposal.display_title}"'
            db.session.add(create_ticket(current_user, proposal))

        elif form.enter_lottery.data and get_signup_state() == "issue_lottery_tickets":
            msg = f'Entered lottery up for "{proposal.display_title}"'
            db.session.add(create_lottery_ticket(current_user, proposal))

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
        "schedule/item.html",
        proposal=proposal,
        is_fave=is_fave,
        venue_name=venue_name,
        form=form,
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


@schedule.route("/herald")
@v_user_required
def herald_main():
    # In theory this should redirect you based on your shift
    venue_list = ("Stage A", "Stage B", "Stage C")
    return render_template("schedule/herald/main.html", venue_list=venue_list)


class HeraldCommsForm(Form):
    talk_id = HiddenIntegerField()
    may_record = BooleanField("Can this be recorded?")
    update = SubmitField("Update info")

    speaker_here = SubmitField("'Now' Speaker here")


class HeraldStageForm(Form):
    now = FormField(HeraldCommsForm)
    next = FormField(HeraldCommsForm)

    message = StringField("Message")
    send_message = SubmitField("Send message")


@schedule.route("/herald/<string:venue_name>", methods=["GET", "POST"])
@v_user_required
def herald_venue(venue_name):
    def herald_message(message, proposal):
        app.logger.info(f"Creating new message {message}")
        end = proposal.scheduled_time + timedelta(minutes=proposal.scheduled_duration)
        return AdminMessage(
            f"[{venue_name}] -- {message}", current_user, end=end, topic="heralds"
        )

    now, next = (
        Proposal.query.join(Venue, Venue.id == Proposal.scheduled_venue_id)
        .filter(
            Venue.name == venue_name,
            Proposal.is_accepted,
            Proposal.scheduled_time > pendulum.now(event_tz),
            Proposal.scheduled_duration.isnot(None),
            Proposal.hide_from_schedule.isnot(True),
        )
        .order_by(Proposal.scheduled_time)
        .limit(2)
        .all()
    )

    form = HeraldStageForm()

    if form.validate_on_submit():
        if form.now.update.data:
            if form.now.talk_id.data != now.id:
                flash("'now' changed, please refresh")
                return redirect(url_for(".herald_venue", venue_name=venue_name))

            change = "may" if form.now.may_record else "may not"
            msg = herald_message(f"Change: {change} record '{now.title}'", now)
            now.may_record = form.now.may_record.data

        elif form.next.update.data:
            if form.next.talk_id.data != next.id:
                flash("'next' changed, please refresh")
                return redirect(url_for(".herald_venue", venue_name=venue_name))
            change = "may" if form.next.may_record else "may not"
            msg = herald_message(f"Change: {change} record '{next.title}'", next)
            next.may_record = form.next.may_record.data

        elif form.now.speaker_here.data:
            msg = herald_message(f"{now.user.name}, arrived.", now)

        elif form.next.speaker_here.data:
            msg = herald_message(f"{next.user.name}, arrived.", next)

        elif form.send_message.data:
            # in lieu of a better time set TTL to end of next talk
            msg = herald_message(form.message.data, next)

        db.session.add(msg)
        db.session.commit()
        return redirect(url_for(".herald_venue", venue_name=venue_name))

    messages = AdminMessage.get_all_for_topic("heralds")

    form.now.talk_id.data = now.id
    form.now.may_record.data = now.may_record

    form.next.talk_id.data = next.id
    form.next.may_record.data = next.may_record

    return render_template(
        "schedule/herald/venue.html",
        messages=messages,
        venue_name=venue_name,
        form=form,
        now=now,
        next=next,
    )


class GreenroomForm(Form):
    speakers = SelectField("Speaker name")
    arrived = SubmitField("Arrived")

    message = StringField("Message")
    send_message = SubmitField("Send message")


@schedule.route("/greenroom", methods=["GET", "POST"])
@cfp_admin_required
def greenroom():
    def greenroom_message(message):
        app.logger.info(f"Creating new message '{message}'")
        end = datetime.now() + timedelta(hours=1)
        return AdminMessage(
            f"[greenroom] -- {message}", current_user, end=end, topic="heralds"
        )

    show = request.args.get("show", default=10, type=int)
    form = GreenroomForm()

    upcoming = (
        Proposal.query.filter(
            Proposal.type.in_(["talk", "workshop", "youthworkshop", "performance"]),
            Proposal.is_accepted,
            Proposal.scheduled_time > pendulum.now(event_tz),
            Proposal.scheduled_duration.isnot(None),
            Proposal.hide_from_schedule.isnot(True),
        )
        .order_by(Proposal.scheduled_time)
        .limit(show)
        .all()
    )
    form.speakers.choices = [
        (prop.published_names or prop.user.name) for prop in upcoming
    ]

    if form.validate_on_submit():
        app.logger.info(f"{form.speakers.data} arrived.")
        if form.arrived.data:
            msg = greenroom_message(f"{form.speakers.data} arrived.")

        elif form.send_message.data:
            msg = greenroom_message(form.message.data)

        db.session.add(msg)
        db.session.commit()

        return redirect(url_for(".greenroom"))

    messages = AdminMessage.get_all_for_topic("heralds")

    return render_template(
        "schedule/herald/greenroom.html",
        form=form,
        messages=messages,
        upcoming=upcoming,
    )
