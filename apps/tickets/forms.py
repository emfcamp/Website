from flask import Markup, render_template_string, url_for
from flask_login import current_user
from wtforms.validators import (
    DataRequired,
    InputRequired,
    Optional,
    Email,
    ValidationError,
)
from wtforms import (
    SubmitField,
    StringField,
    FieldList,
    FormField,
    HiddenField,
    BooleanField,
)
from wtforms.fields.html5 import EmailField

from models.user import User
from ..common.forms import IntegerSelectField, HiddenIntegerField, Form
from ..common import CURRENCY_SYMBOLS


class TicketAmountForm(Form):
    amount = IntegerSelectField("Number of tickets", [Optional()])
    tier_id = HiddenIntegerField("Price tier", [InputRequired()])


class TicketAmountsForm(Form):
    tiers = FieldList(FormField(TicketAmountForm))
    buy_tickets = SubmitField("Buy Tickets")
    buy_hire = SubmitField("Order")
    buy_other = SubmitField("Buy")
    currency_code = HiddenField("Currency")
    set_currency = StringField("Set Currency", [Optional()])

    def validate_set_currency(form, field):
        if field.data not in CURRENCY_SYMBOLS:
            raise ValidationError("Invalid currency %s" % field.data)


class TicketTransferForm(Form):
    name = StringField("Name", [DataRequired()])
    email = EmailField("Email", [DataRequired()])

    transfer = SubmitField("Transfer Ticket")

    def validate_email(form, field):
        if current_user.email == field.data:
            raise ValidationError("You cannot transfer a ticket to yourself")


class TicketPaymentForm(Form):
    email = EmailField("Email", [Email(), DataRequired()])
    name = StringField("Name", [DataRequired()])
    allow_promo = BooleanField("Send me occasional emails about future EMF events")
    basket_total = HiddenField("basket total")

    gocardless = SubmitField("Pay by Direct Debit")
    banktransfer = SubmitField("Pay by Bank Transfer")
    stripe = SubmitField("Pay by card")

    def validate_email(form, field):
        if current_user.is_anonymous and User.does_user_exist(field.data):
            field.was_duplicate = True
            pay_url = url_for("tickets.pay", flow=form.flow)

            msg = Markup(
                render_template_string(
                    "Account already exists. "
                    'Please <a href="{{ url }}">click here</a> to log in.',
                    url=url_for("users.login", next=pay_url, email=field.data),
                )
            )
            raise ValidationError(msg)


class TicketPaymentShippingForm(TicketPaymentForm):
    address_1 = StringField("Address", [DataRequired()])
    address_2 = StringField("Address", [])
    town = StringField("Town", [DataRequired()])
    postcode = StringField("Postal code", [DataRequired()])
    country = StringField("Country", [DataRequired()])
