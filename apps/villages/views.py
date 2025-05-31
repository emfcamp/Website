from flask import abort, flash, redirect, render_template, request, url_for
from flask.typing import ResponseValue
from flask_login import current_user, login_required
from sqlalchemy import exists, select

from main import db
from models import event_year
from models.cfp import Venue
from models.village import Village, VillageMember, VillageRequirements

from . import load_village, villages
from .forms import VillageForm


@villages.route("/register", methods=["GET", "POST"])
@login_required
def register():
    if current_user.village and current_user.village_membership.admin:
        return redirect(url_for(".edit", year=event_year(), village_id=current_user.village.id))

    form = VillageForm()
    if form.validate_on_submit():
        if Village.get_by_name(form.name.data):
            flash("A village already exists with that name, please choose another")
            return redirect(url_for(".register"))

        village = Village()
        form.populate_obj(village)

        membership = VillageMember(village=village, user=current_user, admin=True)

        venue = Venue(village=village, name=village.name)

        requirements = VillageRequirements(village=village)
        form.populate_obj(requirements)

        db.session.add(village)
        db.session.add(membership)
        db.session.add(requirements)
        db.session.add(venue)
        db.session.commit()

        flash("Your village registration has been received, thanks! You can edit it below.")
        return redirect(url_for(".edit", year=event_year(), village_id=village.id))

    return render_template("villages/register.html", form=form)


@villages.route("/")
def villages_redirect():
    return redirect(url_for(".main", year=event_year()))


@villages.route("/<int:year>")
def main(year):
    if year != event_year():
        abort(404)

    villages = list(Village.query.all())
    any_village_located = any(v.location is not None for v in villages)
    return render_template(
        "villages/villages.html",
        villages=villages,
        any_village_located=any_village_located,
    )


@villages.route("/<int:year>/<int:village_id>/edit", methods=["GET", "POST"])
@login_required
def edit(year: int, village_id: int) -> ResponseValue:
    village = load_village(year, village_id, require_admin=True)

    form = VillageForm()
    if form.validate_on_submit():
        if db.session.execute(
            select(exists().where(Village.name == form.name.data, Village.id != village.id))
        ).scalar_one():
            # FIXME: this should be a WTForms validation
            # ALTHOUGH: it's annoying to implement in a wtforms validator since you need a
            # way of telling if the name has changed ;)
            flash("A village already exists with that name, please choose another")
            return redirect(url_for(".register"))

        for venue in village.venues:
            if venue.name == village.name:
                # Rename a village venue if it exists and has the old name.
                venue.name = form.name.data

        form.populate_obj(village)
        db.session.commit()
        flash("Your village registration has been updated.")
        return redirect(url_for(".edit", year=year, village_id=village_id))

    if request.method != "POST":
        form.populate(village)

    return render_template("villages/edit.html", form=form, village=village)
