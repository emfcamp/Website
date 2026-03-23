from flask import (
    flash,
    redirect,
    render_template,
    url_for,
)
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
from wtforms.validators import DataRequired, Optional

from main import db, get_or_404
from models.cfp import SCHEDULE_ITEM_INFOS, Occurrence, Venue
from models.village import Village

from ..common.forms import Form, coerce_optional
from . import (
    admin_required,
    cfp_review,
)

VENUE_TYPE_CHOICES = [(t.type, t.human_type) for t in SCHEDULE_ITEM_INFOS.values()]


class VenueForm(Form):
    name = StringField("Name", [DataRequired()])
    village_id = SelectField("Village", coerce=coerce_optional(int))
    allows_attendee_content = BooleanField("Allows Attendee Content")
    location_lat = FloatField("Latitude")
    location_lon = FloatField("Longitude")
    allowed_types = SelectMultipleField("Allowed for", choices=VENUE_TYPE_CHOICES)
    default_for_types = SelectMultipleField("Default Venue for", choices=VENUE_TYPE_CHOICES)
    capacity = IntegerField("Capacity", validators=[Optional()])
    submit = SubmitField("Save")
    delete = SubmitField("Delete")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "")]
        for v in Village.query.order_by(Village.name).all():
            choices.append((v.id, v.name))
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
def venues():
    venues = Venue.query.order_by(Venue.allows_attendee_content.desc(), Venue.name).all()
    new_venue = Venue()
    form = VenueForm(obj=new_venue)

    if form.validate_on_submit():
        form.populate_obj(new_venue)
        db.session.add(new_venue)
        db.session.commit()
        flash("Saved venue")
        return redirect(url_for(".venues"))

    return render_template("cfp_review/venues/index.html", venues=venues, form=form)


@cfp_review.route("/venues/<int:venue_id>", methods=["GET", "POST"])
@admin_required
def edit_venue(venue_id):
    venue = get_or_404(db, Venue, venue_id)
    form = VenueForm(obj=venue)
    if form.validate_on_submit():
        if form.delete.data:
            occurrences = list(
                db.session.scalars(
                    select(Occurrence)
                    .where(Occurrence.scheduled_venue_id == venue.id)
                    .where(Occurrence.state == "scheduled")
                )
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
