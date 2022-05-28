from flask import (
    render_template,
    redirect,
    url_for,
    flash,
)

from wtforms import StringField, SelectField, BooleanField, SubmitField
from wtforms.validators import DataRequired
from geoalchemy2.shape import to_shape

from main import db
from models.cfp import Venue
from models.village import Village
from . import (
    cfp_review,
    admin_required,
)
from ..common.forms import Form


class VenueForm(Form):
    name = StringField("Name", [DataRequired()])
    village_id = SelectField("Village", choices=[], coerce=int)
    scheduled_content_only = BooleanField("Scheduled Content Only")
    latlon = StringField("Location")
    submit = SubmitField("Save")
    delete = SubmitField("Delete")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(0, "")]
        for v in Village.query.order_by(Village.name).all():
            choices.append((v.id, v.name))
        self.village_id.choices = choices

    def populate_from_venue(self, venue):
        if venue.location is None:
            self.latlon.data = ""
        else:
            latlon = to_shape(venue.location)
            self.latlon.data = "{}, {}".format(latlon.x, latlon.y)

    def populate_obj(self, venue):
        super().populate_obj(venue)

        if self.latlon.data:
            latlon = self.latlon.data.split(",")
            location = f"POINT({latlon[0]} {latlon[1]})"
        else:
            location = None
        venue.location = location

        if self.village_id.data == 0:
            venue.village_id = None
        else:
            venue.village_id = self.village_id.data


@cfp_review.route("/venues", methods=["GET", "POST"])
@admin_required
def venues():
    venues = Venue.query.order_by(Venue.scheduled_content_only.desc(), Venue.name).all()
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
    venue = Venue.query.get_or_404(venue_id)
    form = VenueForm(obj=venue)
    if form.validate_on_submit():
        if form.delete.data:
            db.session.delete(venue)
            db.session.commit()
            flash("Deleted venue")
            return redirect(url_for(".venues"))
        if form.submit.data:
            form.populate_obj(venue)
            db.session.commit()
            flash("Saved venue")
            return redirect(url_for(".venues"))
    else:
        form.populate_from_venue(venue)

    return render_template("cfp_review/venues/edit.html", venue=venue, form=form)
