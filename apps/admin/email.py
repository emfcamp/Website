from flask import flash, redirect, render_template, url_for
from flask.typing import ResponseReturnValue
from sqlalchemy import select
from wtforms import SelectField, StringField, SubmitField
from wtforms.validators import DataRequired
from wtforms.widgets import TextArea

from main import db
from models.content import Proposal
from models.payment import Payment
from models.product import Product
from models.purchase import Purchase
from models.user import User
from models.village import VillageMember

from ..common.email import (
    enqueue_emails,
    format_trusted_html_email,
    format_trusted_plaintext_email,
    preview_trusted_email,
)
from ..common.forms import Form
from ..config import config
from . import admin


class EmailComposeForm(Form):
    subject = StringField("Subject", [DataRequired()])
    text = StringField("Text", [DataRequired()], widget=TextArea())
    destination = SelectField("Send to:")
    preview = SubmitField("Preview Email")
    send_preview_address = StringField("Preview Email Address")
    send_preview = SubmitField("Send Preview Email")
    send = SubmitField("Send Email")

    def populate_destination_choices(self) -> None:
        static_choices = [
            ("ticket", "Ticketholders"),
            ("purchasers", "Users who made payments"),
            ("cfp", "Accepted CfP"),
            ("ticket_and_cfp", "Ticketholders & Accepted CfP"),
            ("villages", "Village owners"),
        ]

        all_products = db.session.execute(select(Product)).scalars()
        claimable_products = sorted(
            (p for p in all_products if p.get_attribute("is_redeemable")), key=lambda p: p.name
        )
        unclaimed_choices = []
        for product in claimable_products:
            unclaimed_choices.append(
                (f"unclaimed:{product.name}", f"Users who have unclaimed Product {product.display_name}")
            )
        self.destination.choices = static_choices + unclaimed_choices


def product_from_dest(dest: str) -> Product:
    product_slug = dest[len("unclaimed:") :]
    product = db.session.execute(select(Product).where(Product.name == product_slug)).scalar_one_or_none()
    if product is None:
        raise ValueError(f"No such product {product_slug}")
    return product


def get_users(dest: str) -> list[User]:
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
        query = query.join(User.proposals).where(Proposal.state.in_({"accepted", "finalised"}))
    elif dest == "villages":
        query = query.join(User.village_membership).where(VillageMember.admin == True)
    elif dest.startswith("unclaimed:"):
        product = product_from_dest(dest)
        query = (
            query.join(User.owned_purchases)
            .where(
                Purchase.product_id == product.id, Purchase.is_paid_for == True, Purchase.redeemed == False
            )
            .group_by(User.id)
        )
    else:
        raise ValueError(f"Invalid email destination set: {dest}")

    return list(db.session.scalars(query.distinct()).unique())


def get_email_reason(dest: str) -> str:
    event = f"Electromagnetic Field {config.event_year}"
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
    if dest.startswith("unclaimed:"):
        product = product_from_dest(dest)
        return f"You're receiving this email because you have purchased {product.display_name} but have not yet redeemed your purchase."
    raise ValueError(f"Invalid email destination set: {dest}")


@admin.route("/email", methods=["GET", "POST"])
def email() -> ResponseReturnValue:
    # This function is almost identical to apps.villages.admin.admin_email_owners, consider updating there too
    form = EmailComposeForm()
    form.populate_destination_choices()
    if form.validate_on_submit():
        users: list[User]
        if form.destination.data == "ticket_and_cfp":
            users = list(set(get_users("ticket")) | set(get_users("cfp")))
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
            assert form.text.data  # DataRequired()
            assert form.subject.data  # DataRequired()
            body: str = form.text.data
            subject: str = form.subject.data
            enqueue_emails(
                users=users,
                from_email=config.from_email("CONTACT_EMAIL"),
                subject=subject,
                text_body=format_trusted_plaintext_email(body),
                html_body=format_trusted_html_email(body, subject, reason=reason),
                priority=2,
                bulk=True,
            )
            db.session.commit()
            flash(f"Email queued for sending to {len(users)} users")
            return redirect(url_for(".email"))

    return render_template("admin/email.html", form=form)
