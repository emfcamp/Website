from . import admin
from flask import render_template, redirect, flash, url_for
from wtforms import SubmitField, StringField, SelectField
from wtforms.validators import DataRequired
from wtforms.widgets import TextArea
from models.user import User
from models.cfp import Proposal
from models.payment import Payment
from models.village import VillageMember
from ..common.forms import Form
from ..common.email import (
    format_trusted_html_email,
    enqueue_trusted_emails,
    preview_trusted_email,
)


class EmailComposeForm(Form):
    subject = StringField("Subject", [DataRequired()])
    text = StringField("Text", [DataRequired()], widget=TextArea())
    destination = SelectField(
        "Send to:",
        choices=[
            ("all", "Registered users"),
            ("ticket", "Ticketholders"),
            ("purchasers", "Users who made payments"),
            ("cfp", "Accepted CfP"),
            ("villages", "Village owners"),
        ],
    )
    preview = SubmitField("Preview Email")
    send_preview_address = StringField("Preview Email Address")
    send_preview = SubmitField("Send Preview Email")
    send = SubmitField("Send Email")


def get_query(dest):
    if dest == "all":
        return User.query
    elif dest == "ticket":
        return (
            User.query.join(User.owned_purchases)
            .filter_by(type="admission_ticket", is_paid_for=True)
            .group_by(User.id)
        )
    elif dest == "purchasers":
        return User.query.join(User.payments).filter(Payment.state == "paid")
    elif dest == "cfp":
        return User.query.join(User.proposals).filter(
            Proposal.state.in_(("accepted", "finished"))
        )
    elif dest == "villages":
        return User.query.join(User.village_membership).filter(VillageMember.admin)


@admin.route("/email", methods=["GET", "POST"])
def email():
    form = EmailComposeForm()
    if form.validate_on_submit():
        users = get_query(form.destination.data).distinct()
        if form.preview.data is True:
            return render_template(
                "admin/email.html",
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
                "admin/email.html",
                html=format_trusted_html_email(form.text.data, form.subject.data),
                form=form,
                count=users.count(),
            )

        if form.send.data is True:
            enqueue_trusted_emails(users, form.subject.data, form.text.data)
            flash("Email queued for sending to %s users" % users.count())
            return redirect(url_for(".email"))

    return render_template("admin/email.html", form=form)
