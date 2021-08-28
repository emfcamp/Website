""" Villages admin.

    NOTE: make sure all admin views are tagged with the @village_admin_required decorator
"""
from flask import render_template, abort
import markdown
from inlinestyler.utils import inline_css
from flask import render_template, redirect, flash, url_for, Markup
from flask import current_app as app
from flask_mail import Message
from wtforms import SubmitField, StringField, SelectField
from wtforms.validators import DataRequired
from wtforms.widgets import TextArea
from ..common.forms import Form

from main import db, mail
from models.village import Village, VillageMember
from models.user import User
from models.email import EmailJob, EmailJobRecipient

from ..common import require_permission
from . import villages

village_admin_required = require_permission("villages")


def format_html_email(markdown_text, subject):
    extensions = ["markdown.extensions.nl2br", "markdown.extensions.smarty"]
    markdown_html = Markup(markdown.markdown(markdown_text, extensions=extensions))
    return inline_css(
        render_template(
            "admin/email/email_template.html", subject=subject, content=markdown_html
        )
    )


def format_plaintext_email(markdown_text):
    return markdown_text


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
                html=format_html_email(form.text.data, form.subject.data),
                form=form,
                count=users.count(),
            )

        if form.send_preview.data is True:
            subject = "[PREVIEW] " + form.subject.data
            formatted_html = format_html_email(form.text.data, subject)
            preview_email = form.send_preview_address.data

            with mail.connect() as conn:
                msg = Message(subject, sender=app.config["CONTACT_EMAIL"])
                msg.add_recipient(preview_email)
                msg.body = format_plaintext_email(form.text.data)
                msg.html = formatted_html
                conn.send(msg)

            flash("Email preview sent to %s" % preview_email)
            return render_template(
                "villages/admin/email.html",
                html=formatted_html,
                form=form,
                count=users.count(),
            )

        if form.send.data is True:
            job = EmailJob(
                form.subject.data,
                format_plaintext_email(form.text.data),
                format_html_email(form.text.data, form.subject.data),
            )
            db.session.add(job)

            for user in users:
                db.session.add(EmailJobRecipient(job, user))
            db.session.commit()
            flash("Email queued for sending to %s users" % users.count())
            return redirect(url_for(".admin_email_owners"))

    return render_template("villages/admin/email.html", form=form)
