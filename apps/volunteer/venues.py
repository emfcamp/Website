# encoding=utf-8
from flask import flash, redirect, render_template, url_for

from . import volunteer, v_admin_required
from .controllers.venue import (
    get_venues, create_new_from_form, init_form_with_venue,
    VenueForm, update_venue_from_form
)

@v_admin_required
@volunteer.route('/venues')
def venue_list():
    return render_template('volunteer/venue.html', venues=get_venues())

@v_admin_required
@volunteer.route('/venues/<int:venue_id>', methods=['GET', 'POST'])
def venue(venue_id):
    form = VenueForm()

    if form.validate_on_submit():
        venue = update_venue_from_form(form, venue_id)
        flash('Venue, {}, updated!'.format(venue.name))
        return redirect(url_for('.venue_list'))

    form = init_form_with_venue(form, venue_id)
    return render_template('volunteer/venue-form.html', new_venue=True, form=form)

@v_admin_required
@volunteer.route('/venues/new', methods=['GET', 'POST'])
def new_venue():
    form = VenueForm()

    if form.validate_on_submit():
        venue = create_new_from_form(form)
        flash('Created new venue: {}'.format(venue.name))
        return redirect(url_for('.venue_list'))

    return render_template('volunteer/venue-form.html', new_venue=False, form=form)
