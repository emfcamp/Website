from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    request,
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
    return render_template("cfp_review/venues/index.html", venues=venues)


@cfp_review.route("/venues/<int:venue_id>", methods=["GET", "POST"])
@admin_required
def edit_venue(venue_id):
    venue = Venue.query.get_or_404(venue_id)
    form = VenueForm(obj=venue)
    if request.method == "POST":
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

    if venue.location is None:
        form.latlon.data = ""
    else:
        latlon = to_shape(venue.location)
        form.latlon.data = "{}, {}".format(latlon.x, latlon.y)
    
    return render_template("cfp_review/venues/edit.html", venue=venue, form=form)