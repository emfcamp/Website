"""Villages admin.

NOTE: make sure all admin views are tagged with the @village_admin_required decorator
"""

from flask import abort, flash, redirect, render_template, url_for
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
from .forms import AdminVillageForm

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
def admin():
    villages = sorted(Village.query.all(), key=lambda v: v.name)

    return render_template("villages/admin/list.html", villages=villages)


@villages.route("/admin/village/<int:village_id>", methods=["GET", "POST"])
@village_admin_required
def admin_village(village_id):
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    form = AdminVillageForm()

    if form.validate_on_submit():
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


@villages.route("/admin/email-owners", methods=["GET", "POST"])
@village_admin_required
def admin_email_owners():
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
