from collections.abc import Sequence
from typing import Literal

from flask import flash, redirect, render_template, url_for
from sqlalchemy import select
from wtforms import SelectField, StringField, SubmitField
from wtforms.validators import DataRequired
from wtforms.widgets import TextArea

from main import db
from models import event_year
from models.cfp import Proposal
from models.payment import Payment
from models.purchase import Purchase
from models.user import User
from models.village import VillageMember

from ..common.email import (
    enqueue_trusted_emails,
    format_trusted_html_email,
    preview_trusted_email,
)
from ..common.forms import Form
from . import admin


class EmailComposeForm(Form):
    subject = StringField("Subject", [DataRequired()])
    text = StringField("Text", [DataRequired()], widget=TextArea())
    destination = SelectField(
        "Send to:",
        choices=[
            ("ticket", "Ticketholders"),
            ("purchasers", "Users who made payments"),
            ("cfp", "Accepted CfP"),
            ("ticket_and_cfp", "Ticketholders & Accepted CfP"),
            ("villages", "Village owners"),
        ],
    )
    preview = SubmitField("Preview Email")
    send_preview_address = StringField("Preview Email Address")
    send_preview = SubmitField("Send Preview Email")
    send = SubmitField("Send Email")


def get_users(dest: Literal["ticket", "cfp", "purchasers", "villages"]) -> Sequence[User]:
    query = select(User)
    if dest == "ticket":
        query = (
            query.join(User.owned_purchases)
            .where(Purchase.type == "admission_ticket", Purchase.is_paid_for == True)
            .group_by(User.id)
        )
    elif dest == "purchasers":
        query = query.join(User.payments).where(Payment.state == "paid")
    elif dest == "cfp":
        query = query.join(User.proposals).where(Proposal.is_accepted)
    elif dest == "villages":
        query = query.join(User.village_membership).where(VillageMember.admin == True)
    else:
        raise ValueError(f"Invalid email destination set: {dest}")

    return db.session.execute(query.distinct()).scalars().all()


def get_email_reason(dest: str) -> str:
    event = f"Electromagnetic Field {event_year()}"
    if dest == "ticket":
        return f"You're receiving this email because you have a ticket for {event}."
    if dest == "purchasers":
        return f"You're receiving this email because you made a payment to {event}."
    if dest == "cfp":
        return f"You're receiving this email because you have an accepted proposal in the {event} Call for Participation."
    if dest == "villages":
        return f"You're receiving this email because you have registered a village for {event}."
    if dest == "ticket_and_cfp":
        return (
            f"You're receiving this email because you have a ticket or a talk/workshop accepted for {event}."
        )
    raise ValueError(f"Invalid email destination set: {dest}")


@admin.route("/email", methods=["GET", "POST"])
def email():
    form = EmailComposeForm()
    if form.validate_on_submit():
        if form.destination.data == "ticket_and_cfp":
            users = set()
            users.update(get_users("ticket"))
            users.update(get_users("cfp"))
        else:
            users = get_users(form.destination.data)

        reason = get_email_reason(form.destination.data)

        if form.preview.data is True:
            return render_template(
                "admin/email.html",
                html=format_trusted_html_email(form.text.data, form.subject.data, reason=reason),
                form=form,
                count=len(users),
            )

        if form.send_preview.data is True:
            preview_trusted_email(form.send_preview_address.data, form.subject.data, form.text.data)

            flash(f"Email preview sent to {form.send_preview_address.data}")
            return render_template(
                "admin/email.html",
                html=format_trusted_html_email(
                    form.text.data,
                    form.subject.data,
                    reason=reason,
                ),
                form=form,
                count=len(users),
            )

        if form.send.data is True:
            enqueue_trusted_emails(
                users,
                form.subject.data,
                form.text.data,
                reason=reason,
            )
            flash(f"Email queued for sending to {len(users)} users")
            return redirect(url_for(".email"))

    return render_template("admin/email.html", form=form)
