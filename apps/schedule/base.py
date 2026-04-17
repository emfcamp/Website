import random
from collections import defaultdict
from datetime import datetime, timedelta
from itertools import groupby

import pendulum
from flask import abort, flash, redirect, render_template, request, url_for
from flask import current_app as app
from flask.typing import ResponseReturnValue
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from wtforms import (
    FieldList,
    FormField,
    HiddenField,
    SelectField,
    StringField,
    SubmitField,
)
from wtforms.validators import InputRequired

from main import db, get_or_404
from models.admin_message import AdminMessage
from models.content import (
    SCHEDULE_ITEM_INFOS,
    Occurrence,
    Proposal,
    ScheduleItem,
    ScheduleItemType,
    Venue,
)
from models.content.lottery import (
    Lottery,
    LotteryEntry,
    LotteryEntryState,
)
from models.user import generate_api_token

from ..cfp_review import admin_required as cfp_admin_required
from ..common import feature_enabled, feature_flag
from ..common.fields import HiddenIntegerField
from ..common.forms import Form
from ..config import config
from ..volunteer import v_user_required
from . import event_tz, schedule
from .data import ScheduleFilter, get_upcoming
from .historic import historic_talk_data, item_historic, talks_historic

# This controls both which types show on lineup and favourites,
# and in which order they are presented.
LINEUP_TYPE_ORDER: list[ScheduleItemType] = [
    "talk",
    "workshop",
    "youthworkshop",
    "performance",
]


@schedule.route("/schedule/")
def main():
    return redirect(url_for(".main_year", year=config.event_year))


@schedule.route("/schedule/<int:year>")
def main_year(year):
    # Do we want to show the current year's schedule from the DB,
    # or a previous year's from the static archive?
    if year == config.event_year:
        if feature_enabled("SCHEDULE"):
            # Schedule is ready, show it
            return schedule_current()
        if feature_enabled("LINE_UP"):
            # Show the lineup (list of talks without times/venues)
            return line_up()
        # No schedule should be shown yet.
        return render_template("schedule/no-schedule.html")
    return talks_historic(year)


def schedule_current():
    token = None
    if current_user.is_authenticated:
        token = generate_api_token(app.config["SECRET_KEY"], current_user.id)

    return render_template(
        "schedule/user_schedule.html",
        token=token,
        debug=app.config.get("DEBUG"),
        year=config.event_year,
    )


# FIXME this should probably work for other years
@schedule.route("/schedule/line-up/2026")
def line_up() -> ResponseReturnValue:
    schedule_items: list[ScheduleItem] = list(
        db.session.scalars(
            select(ScheduleItem)
            .where(ScheduleItem.type.in_(LINEUP_TYPE_ORDER))
            .where(ScheduleItem.state == "published")
            .where(ScheduleItem.official_content == True)
            # ensure consistent shuffle when unchanged
            .order_by(ScheduleItem.id)
        )
    )

    # Shuffle the order, but keep it fixed per-user
    # (Because we don't want a bias in starring)
    random.Random(current_user.get_id()).shuffle(schedule_items)
    # sort is stable so this keeps the shuffle within a type
    schedule_items.sort(key=lambda si: si.type)

    # We can't use jinja's groupby directly because we want to use
    # LINEUP_TYPE_ORDER and it accepts an attribute, not a lambda.
    grouped_schedule_items = {k: list(g) for k, g in groupby(schedule_items, key=lambda si: si.type)}

    ordered_type_infos = [SCHEDULE_ITEM_INFOS[t] for t in LINEUP_TYPE_ORDER]

    return render_template(
        "schedule/line-up.html",
        grouped_schedule_items=grouped_schedule_items,
        ordered_type_infos=ordered_type_infos,
    )


@schedule.route("/schedule/add-favourite", methods=["POST"])
def add_favourite():
    if not current_user.is_authenticated:
        abort(401)

    proposal_id = int(request.form["fave"])
    proposal = get_or_404(db, Proposal, proposal_id)
    if proposal in current_user.favourites:
        current_user.favourites.remove(proposal)
    else:
        current_user.favourites.append(proposal)

    db.session.commit()
    return redirect(url_for(".main_year", year=config.event_year) + f"#proposal-{proposal.id}")


@schedule.route("/favourites", methods=["GET", "POST"])
@feature_flag("LINE_UP")
def favourites() -> ResponseReturnValue:
    if (request.method == "POST") and current_user.is_authenticated:
        proposal_id = int(request.form["fave"])
        proposal = get_or_404(db, Proposal, proposal_id)
        if proposal in current_user.favourites:
            current_user.favourites.remove(proposal)
        else:
            current_user.favourites.append(proposal)

        db.session.commit()
        return redirect(url_for(".favourites") + f"#proposal-{proposal.id}")

    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".favourites")))

    schedule_items = [si for si in current_user.favourites if si.state == "published"]
    schedule_items.sort(key=lambda si: si.type)
    grouped_schedule_items = {k: list(g) for k, g in groupby(schedule_items, key=lambda si: si.type)}

    token = generate_api_token(app.config["SECRET_KEY"], current_user.id)

    ordered_type_infos = [SCHEDULE_ITEM_INFOS[t] for t in LINEUP_TYPE_ORDER]

    return render_template(
        "schedule/favourites.html",
        grouped_schedule_items=grouped_schedule_items,
        token=token,
        ordered_type_infos=ordered_type_infos,
    )


class OccurrenceForm(Form):
    occurrence_id = HiddenIntegerField("Occurrence ID", [InputRequired()])
    get_ticket = SubmitField("Get ticket")
    enter_lottery = SubmitField("Enter lottery")
    ticket_count = SelectField("How many tickets?", coerce=int, default=1)


class ScheduleItemForm(Form):
    toggle_favourite = SubmitField("Favourite")


@schedule.route("/schedule/<int:year>/<int:schedule_item_id>", methods=["GET", "POST"])
@schedule.route("/schedule/<int:year>/<int:schedule_item_id>-<slug>", methods=["GET", "POST"])
def item(year: int, schedule_item_id: int, slug: str | None = None) -> ResponseReturnValue:
    """Display a detail page for a schedule item"""
    if year == config.event_year:
        return item_current(year, schedule_item_id, slug)
    return item_historic(year, schedule_item_id, slug)


def item_current(year: int, schedule_item_id: int, slug: str | None = None) -> ResponseReturnValue:
    """Display a detail page for a schedule item from the current event"""
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)
    if schedule_item.state != "published":
        abort(404)

    if slug != schedule_item.slug:
        return redirect(
            url_for(".item", year=year, schedule_item_id=schedule_item.id, slug=schedule_item.slug)
        )

    if current_user.is_anonymous:
        # None of the form applies to anonymous users
        return render_template(
            "schedule/item.html",
            schedule_item=schedule_item,
        )

    occurrences_dict = {o.id: o for o in schedule_item.occurrences}
    occurrence_forms = {}
    lottery_entry = None
    for occurrence in schedule_item.occurrences:
        occurrence_form = OccurrenceForm()
        occurrence_form.occurrence_id.data = occurrence.id

        if schedule_item.type_info.supports_lottery and occurrence.lottery:
            lottery_entry = current_user.get_lottery_entry_for_occurrence(occurrence)
            if lottery_entry:
                occurrence_form.ticket_count.data = lottery_entry.ticket_count
                if lottery_entry.state == "cancelled":
                    occurrence_form.enter_lottery.label.text = "Re-enter lottery"
                else:
                    occurrence_form.enter_lottery.label.text = "Update ticket count"
                if lottery_entry.state == "valid-tickets":
                    occurrence_form.enter_lottery.label.text = "Update ticket count"

            if schedule_item.type == "youthworkshop":
                # FIXME: is this because we don't count adults for these events?
                occurrence_form.ticket_count.label.text = "How many under-12 tickets?"

            max_tickets = occurrence.lottery.max_tickets_per_entry
            if occurrence.lottery.state == "allow-entry":
                # FIXME: this doesn't (and can't) take into account reserved_tickets
                max_tickets = min([max_tickets, occurrence.lottery.get_lottery_capacity()])

            occurrence_form.ticket_count.choices = [(str(i), str(i)) for i in range(1, max_tickets + 1)]

        occurrence_forms[occurrence.id] = occurrence_form

    schedule_item_form = ScheduleItemForm()

    is_fave = schedule_item in current_user.favourites

    # Peek at the form data to determine which one to use
    if request.form.get("toggle_favourite") is not None:
        if schedule_item_form.validate_on_submit():
            msg = None
            if schedule_item_form.toggle_favourite.data:
                if is_fave:
                    current_user.favourites.remove(schedule_item)
                    msg = f'Removed "{schedule_item.title}" from favourites'
                else:
                    current_user.favourites.append(schedule_item)
                    msg = f'Added "{schedule_item.title}" to favourites'

            db.session.commit()
            if msg:
                flash(msg)
            return redirect(url_for(".lotteries"))

    elif occurrence_id := request.form.get("occurrence_id"):
        occurrence = occurrences_dict[int(occurrence_id)]
        lottery_entry = current_user.get_lottery_entry_for_occurrence(occurrence)
        occurrence_form = occurrence_forms[int(occurrence_id)]

        if occurrence_form.validate_on_submit():
            msg = None
            if lottery_entry:
                assert occurrence.lottery
                if occurrence_form.enter_lottery.data:
                    if occurrence.lottery.state != "allow-entry":
                        abort(400)
                    if lottery_entry.state == "cancelled":
                        lottery_entry.reenter_lottery()
                        msg = f'Re-entered lottery for "{schedule_item.title}" tickets'
                    else:
                        msg = "Updated ticket count"
                    lottery_entry.ticket_count = occurrence_form.ticket_count.data

                elif occurrence_form.get_ticket.data:
                    lottery_entry.ticket_count = occurrence_form.ticket_count.data
                    if lottery_entry.state != "valid-tickets":
                        msg = f'Issued ticket for "{schedule_item.title}"'
                        lottery_entry.change_state("valid-tickets")
                    else:
                        msg = "Updated ticket count"
                    lottery_entry.generate_codes()

            elif occurrence_form.get_ticket.data or occurrence_form.enter_lottery.data:
                assert occurrence.lottery
                # This sets the state automatically
                lottery_entry = LotteryEntry.create_entry(
                    current_user, occurrence.lottery, occurrence_form.ticket_count.data
                )

                if lottery_entry.state == "entered":
                    msg = f'Entered lottery for "{schedule_item.title}"'
                else:
                    msg = f'Signed up for "{schedule_item.title}"'

                db.session.add(lottery_entry)

            db.session.commit()
            if msg:
                flash(msg)
            return redirect(url_for(".lotteries"))

    return render_template(
        "schedule/item.html",
        schedule_item=schedule_item,
        is_fave=is_fave,
        schedule_item_form=schedule_item_form,
        occurrences_dict=occurrences_dict,
        occurrence_forms=occurrence_forms,
        lottery_entry=lottery_entry,
    )


@schedule.route("/schedule/lottery/about")
def about_lotteries():
    return render_template("schedule/lotteries_about.html")


class SingleLotteryEntry(Form):
    entry_id = HiddenIntegerField("entry_id")
    cancel = SubmitField("Cancel")


class LotteryEntriesForm(Form):
    entries = FieldList(FormField(SingleLotteryEntry))


@schedule.route("/schedule/lottery", methods=["GET", "POST"])
def lotteries() -> ResponseReturnValue:
    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for("schedule.lotteries")))

    user_entries = sorted(current_user.lottery_entries, key=lambda t: t.rank or 0)

    form = LotteryEntriesForm()

    if request.method == "POST":
        for entry_form in form.entries:
            if entry_form.cancel.data:
                for lottery_entry in user_entries:
                    if lottery_entry.id == entry_form.entry_id.data:
                        lottery_entry.cancel()
                        db.session.commit()
                        return redirect(url_for(".lottery_entries"))

        abort(400)

    entries_dict: dict[LotteryEntryState, dict[ScheduleItemType, list[LotteryEntry]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for lottery_entry in user_entries:
        form.entries.append_entry()
        form.entries[-1].entry_id.data = lottery_entry.id
        lottery_entry._form = form.entries[-1]
        entries_dict[lottery_entry.state][lottery_entry.schedule_item.type].append(lottery_entry)

    lotteries: list[Lottery] = list(
        db.session.scalars(
            select(Lottery)
            .where(Lottery.state == "allow-entry")
            .options(
                selectinload(Lottery.occurrence),
                selectinload(Occurrence.schedule_item),
            )
        )
    )
    open_lotteries = {k: list(g) for k, g in groupby(lotteries, lambda lottery: lottery.schedule_item.type)}

    return render_template(
        "schedule/lottery_entries.html", entries_dict=entries_dict, open_lotteries=open_lotteries, form=form
    )


@schedule.route("/api/schedule/lottery/<int:entry_id>/cancel", methods=["POST"])
def cancel_lottery_entry(entry_id: int) -> ResponseReturnValue:
    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for("schedule.lottery_entries")))

    lottery_entry = get_or_404(db, LotteryEntry, entry_id)

    if lottery_entry.user != current_user:
        abort(401)

    lottery_entry.cancel()
    app.logger.info(f"Cancelling lottery entry {entry_id} by user {current_user}")
    db.session.commit()

    return redirect(url_for(".lottery_entries"))


@schedule.route("/now-and-next")
def now_and_next() -> ResponseReturnValue:
    filter = ScheduleFilter.from_request()
    per_venue_limit = int(request.args.get("limit", 2))
    venue_slug_sids = get_upcoming(filter, per_venue_limit)

    admin_messages = AdminMessage.get_visible_messages()
    for msg in admin_messages:
        flash(msg.message)

    if request.args.get("fullscreen", default=False, type=bool):
        template = "schedule/now-and-next-fullscreen.html"
    else:
        template = "schedule/now-and-next.html"

    return render_template(template, venues=filter.venues, venue_slug_sids=venue_slug_sids)


@schedule.route("/time-machine")
def time_machine():
    # now = pendulum.datetime(2018, 8, 31, 12, 00, tz=event_tz)
    now = pendulum.now(event_tz)
    now_time = now.time()
    now_weekday = now.weekday()

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
            t for t in talks if t["end_date"].weekday() == now_weekday and t["end_date"].time() >= now_time
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
def herald_main() -> ResponseReturnValue:
    # In theory this should redirect you based on your shift
    venue_list = ("Stage A", "Stage B", "Stage C")
    return render_template("schedule/herald/main.html", venue_list=venue_list)


class HeraldCommsForm(Form):
    occurrence_id = HiddenIntegerField()
    video_privacy = SelectField(
        "Recording",
        choices=[
            ("public", "Stream and record"),
            ("review", "Do not stream, and do not publish until reviewed"),
            ("none", "Do not stream or record"),
        ],
    )
    update = SubmitField("Update info")

    speaker_here = SubmitField("Speaker has arrived")


class HeraldStageForm(Form):
    now = FormField(HeraldCommsForm)
    next = FormField(HeraldCommsForm)

    message = StringField("Message")
    send_message = SubmitField("Send message")


@schedule.route("/herald/<string:venue_name>", methods=["GET", "POST"])
@v_user_required
def herald_venue(venue_name):
    def herald_message(message, occurrence=None):
        app.logger.info(f"Creating new message {message}")
        if occurrence is None:
            end = datetime.now() + timedelta(days=1)
        else:
            end = occurrence.scheduled_time + timedelta(minutes=occurrence.scheduled_duration)
        return AdminMessage(f"[{venue_name}] -- {message}", current_user, end=end, topic="heralds")

    venue = Venue.query.filter_by(name=venue_name).one()
    occurrences = list(
        db.session.scalars(
            select(Occurrence)
            .where(Occurrence.scheduled_venue == venue)
            .where(Occurrence.schedule_item.has(ScheduleItem.state == "published"))
            .where(Occurrence.state == "scheduled")
            .where(Occurrence.scheduled_time > pendulum.now(event_tz))
            .order_by(Occurrence.scheduled_time)
            .limit(2)
            .options(selectinload(Occurrence.schedule_item))
        )
    )
    now, next = (occurrences + [None, None])[:2]

    form = HeraldStageForm()

    if form.validate_on_submit():
        if form.now.update.data:
            if now is None or form.now.occurrence_id.data != now.id:
                flash("'now' changed, please refresh")
                return redirect(url_for(".herald_venue", venue_name=venue_name))

            msg = herald_message(
                f"Change: video privacy '{now.video_privacy}' for '{now.schedule_item.title}'", now
            )
            now.video_privacy = form.now.video_privacy.data

        elif form.next.update.data:
            if next is None or form.next.occurrence_id.data != next.id:
                flash("'next' changed, please refresh")
                return redirect(url_for(".herald_venue", venue_name=venue_name))

            msg = herald_message(
                f"Change: video privacy '{now.video_privacy}' for '{next.schedule_item.title}'", next
            )
            # In theory this allows a herald to set any video_privacy for an Occurrence
            # they can change the time/venue for, but let's not worry about that
            next.video_privacy = form.next.video_privacy.data

        elif form.now.speaker_here.data:
            msg = herald_message(f"{now.names}, arrived.", now)

        elif form.next.speaker_here.data:
            msg = herald_message(f"{next.names}, arrived.", next)

        elif form.send_message.data:
            msg = herald_message(form.message.data)

        db.session.add(msg)
        db.session.commit()
        return redirect(url_for(".herald_venue", venue_name=venue_name))

    messages = AdminMessage.get_all_for_topic("heralds")

    if now:
        form.now.occurrence_id.data = now.id
        form.now.video_privacy.data = now.video_privacy

    if next:
        form.next.occurrence_id.data = next.id
        form.next.video_privacy.data = next.video_privacy

    return render_template(
        "schedule/herald/venue.html",
        messages=messages,
        venue_name=venue_name,
        form=form,
        now=now,
        next=next,
    )


class GreenroomArrivedForm(Form):
    speakers = SelectField("Speaker name")
    arrived = SubmitField("Arrived")


class GreenroomMessageForm(Form):
    message = StringField("Message")
    send_message = SubmitField("Send message")


@schedule.route("/greenroom", methods=["GET", "POST"])
@cfp_admin_required
def greenroom():
    def greenroom_message(message):
        app.logger.info(f"Creating new message '{message}'")
        end = datetime.now() + timedelta(hours=1)
        return AdminMessage(f"[greenroom] -- {message}", current_user, end=end, topic="heralds")

    show = request.args.get("show", default=10, type=int)
    arrived_form = GreenroomArrivedForm()
    message_form = GreenroomMessageForm()

    # NB we show hidden schedule items to the green room currently
    upcoming = list(
        db.session.scalars(
            select(Occurrence)
            .where(Occurrence.state == "scheduled")
            .where(
                Occurrence.schedule_item.has(
                    ScheduleItem.type.in_({"talk", "workshop", "youthworkshop", "performance"}),
                )
            )
            .where(Occurrence.scheduled_time > pendulum.now(event_tz))
            .order_by(Occurrence.scheduled_time)
            .limit(show)
        )
    )
    arrived_form.speakers.choices = [occurrence.schedule_item.names for occurrence in upcoming]

    if arrived_form.arrived.data:
        if arrived_form.validate_on_submit():
            app.logger.info(f"{arrived_form.speakers.data} arrived.")
            msg = greenroom_message(f"{arrived_form.speakers.data} arrived.")
            db.session.add(msg)
            db.session.commit()

            flash(f"Marked {arrived_form.speakers.data} as arrived")
            return redirect(url_for(".greenroom"))

    elif message_form.send_message.data:
        if message_form.validate_on_submit():
            msg = greenroom_message(message_form.message.data)
            db.session.add(msg)
            db.session.commit()

            flash("Message sent")
            return redirect(url_for(".greenroom"))

    messages = AdminMessage.get_all_for_topic("heralds")

    return render_template(
        "schedule/herald/greenroom.html",
        arrived_form=arrived_form,
        message_form=message_form,
        messages=messages,
        upcoming=upcoming,
    )


@schedule.route("/schedule/workshop-steward")
@v_user_required
def workshop_steward_main():
    # TODO: support any venue types that might support lottery?

    workshop_venues = Venue.query.filter(Venue.allowed_types.any("workshop")).all()
    youthworkshop_venues = Venue.query.filter(Venue.allowed_types.any("youthworkshop")).all()

    return render_template(
        "schedule/workshop-steward/main.html",
        workshop_venues=workshop_venues,
        youthworkshop_venues=youthworkshop_venues,
    )


@schedule.route("/schedule/workshop-steward/<int:venue_id>")
@v_user_required
def workshop_steward_venue(venue_id: int) -> ResponseReturnValue:
    venue = get_or_404(db, Venue, venue_id)

    occurrences = list(
        db.session.scalars(
            select(Occurrence)
            .where(
                Occurrence.state == "scheduled",
                Occurrence.scheduled_venue_id == venue_id,
                Occurrence.scheduled_time > (pendulum.now(event_tz.zone).naive() - timedelta(hours=1)),
                Occurrence.schedule_item.has(ScheduleItem.official_content == True),
                Occurrence.lottery.has(),
            )
            .order_by(Occurrence.scheduled_time)
        )
    )
    return render_template("schedule/workshop-steward/venue.html", venue=venue, occurrences=occurrences)


class LotteryCheckInEntryCodeForm(Form):
    code = HiddenField("code")
    use_code = SubmitField("Check-in Code")


class LotteryCheckInEntryForm(Form):
    lottery_entry_id = HiddenIntegerField("lottery_entry_id")
    codes = FieldList(FormField(LotteryCheckInEntryCodeForm))
    use_all_codes = SubmitField("Check in all")


class LotteryCheckInForm(Form):
    lottery_entries = FieldList(FormField(LotteryCheckInEntryForm))


@schedule.route("/schedule/workshop-steward/workshop/<int:occurrence_id>", methods=["GET", "POST"])
@v_user_required
def workshop_steward_occurrence(occurrence_id):
    occurrence = get_or_404(db, Occurrence, occurrence_id)
    lottery = occurrence.lottery

    user_role_names = {r.name for r in current_user.volunteer.interested_roles}

    # Require that the user has the appropriate role & only show the attendee list the hour before
    if occurrence.schedule_item.type == "youthworkshop":
        if "Youth Workshop Helper" not in user_role_names:
            abort(401)

    elif occurrence.schedule_item.type == "workshop":
        if "Workshop Steward" not in user_role_names:
            abort(401)

    else:
        abort(401)

    show_list_after = event_tz.localize(occurrence.scheduled_time - pendulum.duration(minutes=60))
    show_list_before = event_tz.localize(
        occurrence.scheduled_time + pendulum.duration(minutes=(occurrence.scheduled_duration + 60))
    )

    if app.config.get("DEBUG") and request.args.get("ignore_time_lock"):
        time_locked = False

    elif show_list_after < pendulum.now(event_tz) < show_list_before:
        time_locked = False

    else:
        flash(f"The attendee list will be visible after {show_list_after}")
        time_locked = True

    # Now actually do the form
    form = LotteryCheckInForm()

    if form.validate_on_submit():
        for entry_form in form.lottery_entries:
            lottery_entry = LotteryEntry.query.get(entry_form.lottery_entry_id.data)
            if entry_form.use_all_codes.data:
                lottery_entry.use_all_codes()
                db.session.commit()
                flash(f"Checked in {lottery_entry.user.name}")
                return redirect(url_for(".workshop_steward", occurrence_id=occurrence_id))

            for code_form in entry_form.codes:
                if code_form.use_code.data:
                    lottery_entry.use_code(code_form.code.data)
                    db.session.commit()
                    flash(f"Used {lottery_entry.user.name}'s code '{code_form.code.data}'")
                    return redirect(url_for(".workshop_steward", occurrence_id=occurrence_id))

    for lottery_entry in lottery.entries:
        if not lottery_entry.ticket_codes:
            continue

        form.lottery_entries.append_entry()
        form.lottery_entries[-1]._lottery_entry = lottery_entry
        form.lottery_entries[-1].lottery_entry_id.data = lottery_entry.id

        for code in lottery_entry.ticket_codes.split(","):
            form.lottery_entries[-1].codes.append_entry()
            form.lottery_entries[-1].codes[-1].code.data = code

    return render_template(
        "schedule/workshop-steward/workshop.html",
        form=form,
        time_locked=time_locked,
        occurrence=occurrence,
        show_list_after=show_list_after,
    )
