"""
Admin views relating to Venues and TimeBlocks.
"""

from collections import defaultdict
from datetime import time
from typing import get_args

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue
from geoalchemy2.shape import from_shape, to_shape
from shapely import Point
from sqlalchemy import select
from wtforms import (
    BooleanField,
    FloatField,
    IntegerField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
)
from wtforms.fields import TimeField
from wtforms.validators import DataRequired, Optional

from main import db, get_or_404
from models.content import SCHEDULE_ITEM_INFOS, Occurrence, Venue
from models.content.schedule import ScheduleItemType
from models.content.venue import TimeBlock
from models.village import Village

from ..cfp.date import CONTENT_DAY_START, content_days, content_timestamp, timestamp_to_content
from ..common.forms import Form, coerce_optional
from ..config import config
from . import (
    admin_required,
    cfp_review,
)


class VenueForm(Form):
    name = StringField("Name", [DataRequired()])
    village_id = SelectField("Village", coerce=coerce_optional(int))
    allows_attendee_content = BooleanField("Allows Attendee Content")
    location_lat = FloatField("Latitude", validators=[Optional()])
    location_lon = FloatField("Longitude", validators=[Optional()])
    capacity = IntegerField("Capacity", validators=[Optional()])
    submit = SubmitField("Save")
    delete = SubmitField("Delete")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "")]
        for v in db.session.query(Village).order_by(Village.name).all():
            choices.append((str(v.id), v.name))
        self.village_id.choices = choices

    def populate(self, venue: Venue) -> None:
        if venue.location is not None:
            latlon = to_shape(venue.location)
            self.location_lat.data = latlon.y
            self.location_lon.data = latlon.x

    def populate_obj(self, venue: Venue) -> None:
        super().populate_obj(venue)

        if self.location_lat.data is not None and self.location_lon.data is not None:
            location = from_shape(Point(self.location_lon.data, self.location_lat.data))
        else:
            location = None
        venue.location = location


@cfp_review.route("/venues", methods=["GET", "POST"])
@admin_required
def venues() -> ResponseReturnValue:
    venues_query = db.session.query(Venue).order_by(Venue.name)
    if not request.args.get("all"):
        venues_query = venues_query.where(Venue.village_id.is_(None))

    venues = venues_query.all()
    new_venue = Venue()
    form = VenueForm(obj=new_venue)

    if form.validate_on_submit():
        form.populate_obj(new_venue)
        db.session.add(new_venue)
        db.session.commit()
        flash("Saved venue")
        return redirect(url_for(".venues"))

    return render_template("cfp_review/venues/index.html", venues=venues, form=form)


@cfp_review.route("/venues/<int:venue_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_venue(venue_id: int) -> ResponseReturnValue:
    venue = get_or_404(db, Venue, venue_id)
    form = VenueForm(obj=venue)
    if form.validate_on_submit():
        if form.delete.data:
            occurrences = list(
                db.session.scalars(select(Occurrence).where(Occurrence.scheduled_venue_id == venue.id))
            )

            if occurrences:
                flash("Cannot delete venue with scheduled content")
                return redirect(url_for(".edit_venue", venue_id=venue_id))

            db.session.delete(venue)
            db.session.commit()
            flash("Deleted venue")
            return redirect(url_for(".venues"))

        if form.submit.data:
            form.populate_obj(venue)
            db.session.commit()
            flash("Saved venue")
            return redirect(url_for(".venues"))

    form.populate(venue)

    return render_template("cfp_review/venues/edit.html", venue=venue, form=form)


class TimeBlockForm(Form):
    start = TimeField("Start time")
    end = TimeField("End time")
    automatic = BooleanField("Enable automatic scheduler")
    type = SelectField("Content type", choices=get_args(ScheduleItemType))

    submit = SubmitField("Save")
    delete = SubmitField("Delete")


class NewTimeBlockForm(TimeBlockForm):
    days = SelectMultipleField("Days")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.days.choices = [(str(i), date.strftime("%a %d %B")) for i, date in enumerate(config.event_days)]


@cfp_review.route("/venues/<int:venue_id>/time-blocks", methods=["GET", "POST"])
@admin_required
def venue_timeblocks(venue_id: int) -> ResponseReturnValue:
    venue = get_or_404(db, Venue, venue_id)

    days = list(content_days())

    new_form = NewTimeBlockForm()

    if new_form.validate_on_submit():
        assert new_form.days.data and new_form.start.data and new_form.end.data
        created = 0
        for day in new_form.days.data:
            time_block = TimeBlock()

            date = days[int(day)][0]

            time_block.start = content_timestamp(date, new_form.start.data)
            time_block.end = content_timestamp(date, new_form.end.data)
            time_block.type = new_form.type.data
            time_block.automatic = new_form.automatic.data
            venue.time_blocks += [time_block]
            created += 1

        db.session.commit()

        flash(f"{created} new time block(s) created")
        return redirect(url_for(".venue_timeblocks", venue_id=venue.id))

    time_blocks_by_day = defaultdict(list)
    for day, (day_start, day_end) in days:
        for b in venue.time_blocks:
            if day_start < b.start <= day_end:
                height = (min(day_end, b.end) - max(day_start, b.start)).seconds * 100 / (24 * 60 * 60)
                top = (max(day_start, b.start) - day_start).seconds * 100 / (24 * 60 * 60)
                time_blocks_by_day[day].append(
                    {
                        "height": height,
                        "top": top,
                        "block": b,
                        "title": SCHEDULE_ITEM_INFOS[b.type].human_type,
                    }
                )

    timeblock_hours = [time(i % 24, 0, 0) for i in range(CONTENT_DAY_START.hour, CONTENT_DAY_START.hour + 24)]

    return render_template(
        "cfp_review/venues/time_blocks.html",
        venue=venue,
        days=[date for date, _ in days],
        new_form=new_form,
        time_blocks_by_day=time_blocks_by_day,
        day_start=CONTENT_DAY_START,
        timeblock_hours=timeblock_hours,
    )


@cfp_review.route("/venues/<int:venue_id>/time-blocks/<int:time_block_id>", methods=["GET", "POST"])
@admin_required
def timeblock_edit(venue_id: int, time_block_id: int) -> ResponseReturnValue:
    venue = get_or_404(db, Venue, venue_id)
    time_block = get_or_404(db, TimeBlock, time_block_id)
    if venue.id != time_block.venue_id:
        abort(404)

    form = TimeBlockForm(obj=time_block)

    day, _ = timestamp_to_content(time_block.start)

    if form.validate_on_submit():
        if form.delete.data:
            db.session.delete(time_block)
            flash("Time block deleted")
        else:
            assert form.start.data and form.end.data
            time_block.start = content_timestamp(day, form.start.data)
            time_block.end = content_timestamp(day, form.end.data)
            time_block.automatic = form.automatic.data
            time_block.type = form.type.data
            flash("Time block updated")

        db.session.commit()
        return redirect(url_for(".venue_timeblocks", venue_id=venue.id))

    return render_template(
        "cfp_review/venues/time_block_edit.html", venue=venue, form=form, time_block=time_block
    )
