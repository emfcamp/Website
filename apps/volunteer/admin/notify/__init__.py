from flask import (
    abort,
    Blueprint,
    render_template,
    redirect,
    session,
    flash,
    url_for,
    request,
)
from flask_login import current_user
from wtforms import SubmitField, StringField
from wtforms.validators import DataRequired
from wtforms.widgets import TextArea

from apps.common import require_permission
from apps.common.forms import Form
from apps.common.email import (
    format_trusted_html_email,
)
from apps.volunteer.admin import volunteer_admin
from apps.volunteer.notify import preview_trusted_notify, enqueue_trusted_notify
from models.volunteer import Volunteer


notify = Blueprint("volunteer_admin_notify", __name__)

# Decorators to require admin permissions
admin_required = require_permission("admin")
volunteer_admin_required = require_permission("volunteer:admin")


@notify.before_request
def notify_require_permission():
    """Require admin permission for everything under /volunteer/admin"""
    if (
        not current_user.is_authenticated
        or not current_user.has_permission("admin")
        or not current_user.has_permission("volunteer:admin")
    ):
        abort(404)


@notify.context_processor
def notify_variables():
    if not request.path.startswith("/volunteer/admin"):
        return {}

    return {
        "admin_view": volunteer_admin.index_view,
        "view_name": request.url_rule.endpoint.replace("volunteer_admin.", "."),
    }


class EmailComposeForm(Form):
    subject = StringField("Subject", [DataRequired()])
    text = StringField("Text", [DataRequired()], widget=TextArea())
    preview = SubmitField("Preview Email")
    send_preview_address = StringField("Preview Email Address")
    send_preview = SubmitField("Send Preview Email")
    send = SubmitField("Send Email")


@notify.route("/", methods=["GET", "POST"])
def main():
    if not session.get("recipients"):
        return redirect(url_for("volunteer_admin_volunteer.index_view"))

    volunteers = Volunteer.query.filter(Volunteer.id.in_(session["recipients"]))

    form = EmailComposeForm()
    if form.validate_on_submit():
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

    return render_template(
        "volunteer/admin/notify.html",
        form=form,
        count=volunteers.count(),
    )
