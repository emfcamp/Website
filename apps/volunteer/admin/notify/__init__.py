from flask import abort, Blueprint, render_template, redirect, session, flash, url_for
from flask_login import current_user
from wtforms import SubmitField, StringField
from wtforms.validators import DataRequired
from wtforms.widgets import TextArea
from models.volunteer import Volunteer
from apps.common.forms import Form
from apps.common.email import (
    format_trusted_html_email,
)
from apps.volunteer.notify import preview_trusted_notify, enqueue_trusted_notify
from apps.common import require_permission

notify = Blueprint("volunteer_admin_notify", __name__)

admin_required = require_permission("admin")  # Decorator to require admin permissions
volunteer_admin_required = require_permission(
    "volunteer:admin"
)  # Decorator to require admin permissions


@notify.before_request
def admin_require_permission():
    """Require admin permission for everything under /volunteer/admin"""
    if (
        not current_user.is_authenticated
        or not current_user.has_permission("admin")
        or not current_user.has_permission("volunteer:admin")
    ):
        abort(404)


class EmailComposeForm(Form):
    subject = StringField("Subject", [DataRequired()])
    text = StringField("Text", [DataRequired()], widget=TextArea())
    preview = SubmitField("Preview Email")
    send_preview_address = StringField("Preview Email Address")
    send_preview = SubmitField("Send Preview Email")
    send = SubmitField("Send Email")


@notify.route("/", methods=["GET", "POST"])
def main():
    form = EmailComposeForm()
    if form.validate_on_submit():
        volunteers = Volunteer.query.filter(Volunteer.id.in_(session["recipients"]))
        if form.preview.data is True:
            return render_template(
                "volunteer/admin/notify.html",
                html=format_trusted_html_email(form.text.data, form.subject.data),
                form=form,
                count=volunteers.count(),
            )

        if form.send_preview.data is True:
            preview_trusted_notify(
                form.send_preview_address.data, form.subject.data, form.text.data
            )

            flash("Email preview sent to %s" % form.send_preview_address.data)
            return render_template(
                "volunteer/admin/notify.html",
                html=format_trusted_html_email(form.text.data, form.subject.data),
                form=form,
                count=volunteers.count(),
            )

        if form.send.data is True:
            enqueue_trusted_notify(volunteers, form.subject.data, form.text.data)
            flash("Email queued for sending to %s volunteers" % volunteers.count())
            return redirect(url_for("volunteer_admin_notify.main"))

    return render_template("volunteer/admin/notify.html", form=form)
