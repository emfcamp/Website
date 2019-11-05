""" Views for dealing with external schedules provided by villages."""

from wtforms import StringField, SubmitField, BooleanField, SelectField
from wtforms.validators import DataRequired, URL
from models.map import MapObject
from flask_login import login_required, current_user
from flask import render_template, redirect, url_for, flash, request, abort

from main import db
from models import event_year
from models.ical import CalendarSource, CalendarEvent

from ..common.forms import Form
from ..common import feature_flag

from . import schedule


@schedule.route("/schedule/<int:year>/external/<int:event_id>", methods=["GET", "POST"])
@schedule.route(
    "/schedule/<int:year>/external/<int:event_id>-<slug>", methods=["GET", "POST"]
)
@feature_flag("LINE_UP")
def item_external(year, event_id, slug=None):
    if year != event_year():
        abort(404)

    event = CalendarEvent.query.get_or_404(event_id)

    if not current_user.is_anonymous:
        is_fave = event in current_user.calendar_favourites
    else:
        is_fave = False

    if (request.method == "POST") and not current_user.is_anonymous:
        if is_fave:
            current_user.calendar_favourites.remove(event)
            msg = 'Removed "%s" from favourites' % event.title
        else:
            current_user.calendar_favourites.append(event)
            msg = 'Added "%s" to favourites' % event.title
        db.session.commit()
        flash(msg)
        return redirect(
            url_for(".item_external", year=year, event_id=event.id, slug=event.slug)
        )

    if slug != event.slug:
        return redirect(
            url_for(".item_external", year=year, event_id=event.id, slug=event.slug)
        )

    return render_template(
        "schedule/item-external.html",
        event=event,
        is_fave=is_fave,
        venue_name=event.venue,
    )


class AddExternalFeedForm(Form):
    url = StringField("URL", [DataRequired(), URL()])
    preview = SubmitField("Preview")


@schedule.route("/schedule/external/feeds", methods=["GET", "POST"])
def external_feeds_redirect():
    return redirect(url_for(".external_feeds"))


@schedule.route("/schedule/publish", methods=["GET", "POST"])
@login_required
@feature_flag("LINE_UP")
def external_feeds():
    form = AddExternalFeedForm()

    if form.validate_on_submit():
        url = form.url.data.strip()
        source = CalendarSource.query.filter_by(
            user_id=current_user.id, url=url
        ).one_or_none()

        if not source:
            source = CalendarSource(url=url, user=current_user)
            db.session.commit()

        return redirect(url_for(".external_feed", source_id=source.id))

    calendars = current_user.calendar_sources
    return render_template(
        "schedule/external/feeds.html", form=form, calendars=calendars
    )


class UpdateExternalFeedForm(Form):
    url = StringField("URL", [DataRequired(), URL()])
    name = StringField("Feed Name", [DataRequired()])
    location = SelectField("Location", [DataRequired()])
    published = BooleanField("Publish events from this feed")
    preview = SubmitField("Preview")
    save = SubmitField("Save")


@schedule.route("/schedule/publish/<int:source_id>", methods=["GET", "POST"])
@login_required
@feature_flag("LINE_UP")
def external_feed(source_id):
    calendar = CalendarSource.query.get(source_id)
    if calendar.user != current_user:
        abort(403)

    choices = sorted([(str(mo.id), mo.name) for mo in MapObject.query])
    choices = [("", "")] + choices

    form = UpdateExternalFeedForm(obj=calendar)
    form.location.choices = choices

    if request.method != "POST":
        if calendar.mapobj:
            form.location.data = str(calendar.mapobj.id)
        else:
            form.location.data = ""

    if form.validate_on_submit():
        if form.save.data:
            calendar.name = form.name.data
            calendar.published = form.published.data

            if form.location.data:
                map_obj_id = int(form.location.data)
                calendar.mapobj = MapObject.query.get(map_obj_id)
            else:
                calendar.mapobj = None

            try:
                calendar.refresh()
            except Exception:
                pass
            db.session.commit()
            return redirect(url_for(".external_feeds"))

        calendar.url = form.url.data

    try:
        alerts = calendar.refresh()
    except Exception:
        alerts = [("danger", "An error occurred trying to load the feed")]
        preview_events = []
    else:
        preview_events = list(calendar.events)

    if not preview_events:
        alerts = [("danger", "We could not load any events from this feed")]

    db.session.rollback()

    return render_template(
        "schedule/external/feed.html",
        form=form,
        calendar=calendar,
        preview_events=preview_events,
        alerts=alerts,
        preview=True,
    )
