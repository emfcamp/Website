""" Villages admin.

    NOTE: make sure all admin views are tagged with the @village_admin_required decorator
"""
from flask import render_template, abort, redirect, flash, url_for
from wtforms import SubmitField, StringField
from wtforms.validators import DataRequired
from wtforms.widgets import TextArea
from ..common.forms import Form
from ..common.email import (
    format_trusted_html_email,
    enqueue_trusted_emails,
    preview_trusted_email,
)

from models.village import Village, VillageMember
from models.user import User

from ..common import require_permission
from . import villages

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


@villages.route("/admin/village/<int:village_id>")
@village_admin_required
def admin_village(village_id):
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    return render_template("villages/admin/info.html", village=village)


@villages.route("/admin/email_owners", methods=["GET", "POST"])
@village_admin_required
def admin_email_owners():
    form = EmailComposeForm()
    if form.validate_on_submit():
        users = (
            User.query.join(User.village_memberships)
            .filter(VillageMember.admin)
            .distinct()
        )
        if form.preview.data is True:
            return render_template(
                "villages/admin/email.html",
                html=format_trusted_html_email(form.text.data, form.subject.data),
                form=form,
                count=users.count(),
            )

        if form.send_preview.data is True:
            preview_trusted_email(
                form.send_preview_address.data, form.subject.data, form.text.data
            )

            flash("Email preview sent to %s" % form.send_preview_address.data)
            return render_template(
                "villages/admin/email.html",
                html=format_trusted_html_email(form.text.data, form.subject.data),
                form=form,
                count=users.count(),
            )

        if form.send.data is True:
            enqueue_trusted_emails(users, form.subject.data, form.text.data)
            flash("Email queued for sending to %s users" % users.count())
            return redirect(url_for(".admin_email_owners"))

    return render_template("villages/admin/email.html", form=form)
