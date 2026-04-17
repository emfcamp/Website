import html

import markdown
import nh3
from flask import abort, flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_required
from markupsafe import Markup
from sqlalchemy import exists, select

from main import db
from models.content import Venue
from models.village import Village, VillageMember

from ..config import config
from . import load_village, villages
from .forms import VillageForm


@villages.route("/register", methods=["GET", "POST"])
@login_required
def register() -> ResponseReturnValue:
    if current_user.village and current_user.village_membership.admin:
        return redirect(url_for(".edit", year=config.event_year, village_id=current_user.village.id))

    if not current_user.has_admission_ticket:
        flash("You can't create a village without a ticket to EMF")
        return redirect(url_for("users.account"))

    form = VillageForm()
    if form.validate_on_submit():
        # Checked by form so should never fail
        assert form.name.data is not None
        if Village.get_by_name(form.name.data):
            # TODO: should probably be a validator, although then you do have to give it
            # a db handle and somehow pass in the current name. WTForms-alchemy has a
            # ModelForm which solves this...
            form.name.errors = ["A village already exists with that name, please choose another"]
        else:
            village = Village()
            form.populate_obj(village)

            membership = VillageMember(village=village, user=current_user, admin=True)

            venue = Venue(village=village, name=village.name)

            db.session.add(village)
            db.session.add(membership)
            db.session.add(venue)
            db.session.commit()

            flash("Your village registration has been received, thanks! You can edit it below.")
            return redirect(url_for(".view", year=config.event_year, village_id=village.id))

    return render_template("villages/register.html", form=form)


@villages.route("/")
def villages_redirect() -> ResponseReturnValue:
    return redirect(url_for(".main", year=config.event_year))


@villages.route("/<int:year>")
def main(year: int) -> ResponseReturnValue:
    if year != config.event_year:
        abort(404)

    villages = list(db.session.execute(select(Village)).scalars().all())
    any_village_located = any(v.location is not None for v in villages)
    return render_template(
        "villages/villages.html",
        villages=villages,
        any_village_located=any_village_located,
    )


@villages.route("/<int:year>/<int:village_id>")
def view(year: int, village_id: int) -> ResponseReturnValue:
    village = load_village(year, village_id)
    show_edit = (
        current_user.is_authenticated
        and current_user.village
        and current_user.village.id == village_id
        and current_user.village_membership.admin
    )

    return render_template(
        "villages/view.html",
        village=village,
        show_edit=show_edit,
        village_long_description_html=(
            render_markdown(village.long_description) if village.long_description else None
        ),
    )


def render_markdown(markdown_text: str) -> Markup:
    """Render untrusted markdown

    This doesn't have access to any templating unlike email markdown
    which is from a trusted user so is pre-processed with jinja.
    """
    extensions = ["markdown.extensions.nl2br", "markdown.extensions.smarty", "tables"]
    content_html = nh3.clean(
        markdown.markdown(markdown_text, extensions=extensions),
        tags=(nh3.ALLOWED_TAGS - {"img"}),
        link_rel="noopener nofollow",  # default includes noreferrer but not nofollow
    )
    inner_html = render_template("sandboxed-iframe.html", body=Markup(content_html))
    iFrame_html = f'<iframe sandbox="allow-scripts allow-top-navigation-by-user-activation" class="embedded-content" srcdoc="{html.escape(inner_html, True)}"></iframe>'
    return Markup(iFrame_html)


@villages.route("/<int:year>/<int:village_id>/edit", methods=["GET", "POST"])
@login_required
def edit(year: int, village_id: int) -> ResponseReturnValue:
    village = load_village(year, village_id, require_admin=True)

    form = VillageForm()
    if request.method == "GET":
        form.populate(village)

    if form.validate_on_submit():
        # Check to see if changed name clashes with another village
        if db.session.execute(
            select(exists().where(Village.name == form.name.data, Village.id != village.id))
        ).scalar_one():
            # TODO: see register()
            form.name.errors = ["A village already exists with that name, please choose another"]
        else:
            # All good, update DB
            for venue in village.venues:
                if venue.name == village.name and form.name.data is not None:
                    # Rename a village venue if it exists and has the old name.
                    venue.name = form.name.data

            form.populate_obj(village)
            db.session.commit()
            flash("Your village registration has been updated.")
            return redirect(url_for(".view", year=year, village_id=village_id))

    return render_template("villages/edit.html", form=form, village=village)
