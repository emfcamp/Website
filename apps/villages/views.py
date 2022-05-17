from flask import render_template, flash, redirect, url_for, abort
from flask_login import login_required, current_user

from models import event_year
from models.village import Village, VillageMember, VillageRequirements
from models.cfp import Venue

from main import db

from . import villages, load_village
from .forms import VillageForm


@villages.route("/register", methods=["GET", "POST"])
@login_required
def register():
    if current_user.village and current_user.village.admin:
        return redirect(
            url_for(
                ".edit", year=event_year(), village_id=current_user.village.village.id
            )
        )

    form = VillageForm()
    if form.validate_on_submit():
        if Village.get_by_name(form.name.data):
            flash("A village already exists with that name, please choose another")
            return redirect(url_for(".register"))

        village = Village(name=form.name.data, description=form.description.data)

        member = VillageMember(village=village, user=current_user, admin=True)

        venue = Venue(village=village, name=village.name)

        requirements = VillageRequirements(
            village=village,
            num_attendees=form.num_attendees.data,
            size_sqm=form.size_sqm.data,
            power_requirements=form.power_requirements.data,
            noise=form.noise.data,
            structures=form.structures.data,
        )
        db.session.add(village)
        db.session.add(member)
        db.session.add(requirements)
        db.session.add(venue)
        db.session.commit()

        flash(
            "Your village registration has been received, thanks! You can edit it below."
        )
        return redirect(url_for(".edit", year=event_year(), village_id=village.id))

    return render_template("villages/register.html", form=form)


@villages.route("/")
def villages_redirect():
    return redirect(url_for(".main", year=event_year()))


@villages.route("/<int:year>")
def main(year):
    if year != event_year():
        abort(404)

    villages = Village.query.all()
    return render_template("villages/villages.html", villages=villages)


@villages.route("/<int:year>/<int:village_id>/edit", methods=["GET", "POST"])
@login_required
def edit(year, village_id):
    village = load_village(year, village_id, require_admin=True)

    form = VillageForm()
    if form.validate_on_submit():
        form.populate_obj(village)
        form.populate_obj(village.requirements)
        db.session.commit()
        flash("Your village registration has been updated.")
        return redirect(url_for(".edit", year=year, village_id=village_id))

    form.populate(village)
    return render_template("villages/edit.html", form=form, village=village)
