"""Villages admin.

NOTE: make sure all admin views are tagged with the @village_admin_required decorator
"""

from flask import abort, flash, redirect, render_template, request, url_for
from flask import current_app as app
from flask.typing import ResponseValue
from sqlalchemy import exists, select
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired
from wtforms.widgets import TextArea

from main import db
from models.user import User
from models.village import Village, VillageMember

from ..common import require_permission
from ..common.email import (
    enqueue_trusted_emails,
    format_trusted_html_email,
    preview_trusted_email,
)
from ..common.forms import Form
from . import villages
from .forms import AdminVillageForm, DeleteVillageForm

village_admin_required = require_permission("villages")


class EmailComposeForm(Form):
    subject = StringField("Subject", [DataRequired()])
    text = StringField("Text", [DataRequired()], widget=TextArea())
    preview = SubmitField("Preview Email")
    send_preview_address = StringField("Preview Email Address")
    send_preview = SubmitField("Send Preview Email")
    send = SubmitField("Send Email")


@villages.route("/admin")
@village_admin_required
def admin() -> ResponseValue:
    villages = sorted(db.session.query(Village).all(), key=lambda v: v.name)

    return render_template("villages/admin/list.html", villages=villages)


@villages.route("/admin/village/<int:village_id>", methods=["GET", "POST"])
@village_admin_required
def admin_village(village_id: int) -> ResponseValue:
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    form = AdminVillageForm()

    if form.validate_on_submit():
        assert form.name.data
        if db.session.execute(
            select(exists().where(Village.name == form.name.data, Village.id != village.id))
        ).scalar_one():
            flash("Another village with that name already exists!", "error")
        else:
            for venue in village.venues:
                if venue.name == village.name:
                    # Rename a village venue if it exists and has the old name.
                    venue.name = form.name.data

            form.populate_obj(village)
            db.session.add(village)
            db.session.commit()

            flash("The village has been updated")
        return redirect(url_for(".admin_village", village_id=village.id))

    form.populate(village)

    return render_template("villages/admin/info.html", village=village, form=form)


@villages.route("/admin/village/<int:village_id>/delete", methods=["GET", "POST"])
@village_admin_required
def delete(village_id: int) -> ResponseValue:
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    form = DeleteVillageForm()
    if form.validate_on_submit():
        app.logger.info(f"Village '{village.name}' (id {village.id}) deleted")
        db.session.delete(village)
        db.session.commit()
        flash("Village deleted")
        return redirect(url_for(".admin"))

    return render_template("villages/admin/delete.html", village=village, form=form)


@villages.route("/admin/village/<int:village_id>/admins", methods=["GET"])
@village_admin_required
def admin_village_admins_get(village_id: int) -> ResponseValue:
    return redirect(url_for(".admin_village", village_id=village_id))


# Note that there are 2 uses of the word admin here.
# 1. the very small number of orga who can access the admin UI and change all villages
# 2. the attendees responsible for a single village who can administer just that village.
# This route is for the former users to use to edit a list of the latter for a village
@villages.route("/admin/village/<int:village_id>/admins", methods=["POST"])
@village_admin_required
def admin_village_admins(village_id: int) -> ResponseValue:
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    if request.form.get("remove"):
        # Remove an admin
        if len(village.admins()) <= 1:
            flash("Can't remove final admin")
        else:
            user_id = int(request.form.get("user_id", 0))
            village_membership = next(
                member for member in village.village_memberships if member.user_id == user_id
            )

            db.session.delete(village_membership)
            db.session.commit()

            flash(f"{village_membership.user.email} has been removed as a village admin")
    elif request.form.get("add"):
        # Add an admin
        user_email = request.form.get("user_email")
        assert user_email
        user = User.get_by_email(user_email)

        if user is None:
            flash(f"No user found with email {user_email}")
            return redirect(url_for(".admin_village", village_id=village.id))

        membership = db.session.query(VillageMember).filter(VillageMember.user == user).first()

        if membership is None:
            db.session.add(VillageMember(village_id=village.id, user=user, admin=True))
            db.session.commit()

            flash(f"{user_email} has been added as a village admin")
            return redirect(url_for(".admin_village", village_id=village.id))

        if membership.village == village:
            membership.admin = True
            db.session.commit()
        else:
            flash(
                f"User with email {user_email} is already a member of the {membership.village.name} village"
            )

    else:
        # Not sure what is being requested here, log an error
        app.logger.warning(f"Request to alter village admins with unexpected params: ${request.form}")
        abort(400)

    # Show the edit page again
    return redirect(url_for(".admin_village", village_id=village.id))


@villages.route("/admin/email-owners", methods=["GET", "POST"])
@village_admin_required
def admin_email_owners() -> ResponseValue:
    form = EmailComposeForm()
    if form.validate_on_submit():
        users = User.query.join(User.village_membership).filter(VillageMember.admin).distinct()
        if form.preview.data is True:
            return render_template(
                "villages/admin/email.html",
                html=format_trusted_html_email(form.text.data, form.subject.data),
                form=form,
                count=users.count(),
            )

        if form.send_preview.data is True:
            preview_trusted_email(form.send_preview_address.data, form.subject.data, form.text.data)

            flash(f"Email preview sent to {form.send_preview_address.data}")
            return render_template(
                "villages/admin/email.html",
                html=format_trusted_html_email(form.text.data, form.subject.data),
                form=form,
                count=users.count(),
            )

        if form.send.data is True:
            enqueue_trusted_emails(users, form.subject.data, form.text.data)
            flash(f"Email queued for sending to {users.count()} users")
            return redirect(url_for(".admin_email_owners"))

    return render_template("villages/admin/email.html", form=form)
