from flask import current_app as app
from flask_login import current_user

from wtforms import SubmitField, StringField
from wtforms.validators import ValidationError

from main import db

from models.volunteers.venue import VolunteerVenue

from ...common.forms import Form, HiddenIntegerField

class VenueForm(Form):
    id = HiddenIntegerField('Id', default=0)
    name = StringField('Name')
    # TODO add some basic validation for maprefs
    mapref = StringField('Map ref')
    create = SubmitField('Save Venue')

    def validate_name(form, field):
        venue = VolunteerVenue.get_by_name(field.data)

        if form.id.data == 0 and venue is not None:
            raise ValidationError('That venue already exists')
        elif venue is not None and form.id.data != venue.id:
            raise ValidationError('A venue with that name already exists')


def create_new_from_form(form):
    venue = VolunteerVenue(name=form.name.data, mapref=form.mapref.data)
    db.session.add(venue)
    db.session.commit()
    app.logger.info('%s created a new venue, %s (id: %s)',
                    current_user.id, venue.name, venue.id)
    return venue

def update_venue_from_form(form, venue_id):
    venue = VolunteerVenue.get_by_id(venue_id)
    venue.name = form.name.data
    venue.mapref = form.mapref.data
    db.session.commit()
    app.logger.info('%s updated venue, %s (id: %s)',
                    current_user.id, venue.name, venue.id)
    return venue

def init_form_with_venue(form, venue_id):
    venue = VolunteerVenue.get_by_id(venue_id)
    form.id.data = venue.id
    form.name.data = venue.name
    form.mapref.data = venue.mapref
    return form

def get_venue_by_id(id):
    return VolunteerVenue.get_by_id(id)

def get_venues():
    return VolunteerVenue.get_all()
