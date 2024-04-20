import requests
from flask import render_template, redirect, flash, url_for, current_app as app
from flask_login import login_required
from wtforms import StringField, SubmitField
from wtforms.validators import ValidationError
from wtforms.fields.html5 import IntegerRangeField

from . import payments
from .common import get_user_payment_or_abort
from ..common.forms import Form
from main import db
from models import RefundRequest
from models.site_state import get_refund_state


@payments.route("/pay/terms")
def terms():
    return render_template("terms.html")


def required_for(currency=None, providers=None):
    def validate(form, field):
        if form._total_amount == form.donation_amount.data:
            return
        if providers is not None and form._provider not in providers:
            return
        if currency is not None and form._currency != currency:
            return
        if not field.data:
            raise ValidationError("This field is required")

    return validate


class RefundRequestForm(Form):
    # We only support UK and international (Euros)
    sort_code = StringField(
        "Sort code", [required_for(currency="GBP", providers=["banktransfer"])]
    )
    account = StringField(
        "Account number", [required_for(currency="GBP", providers=["banktransfer"])]
    )
    iban = StringField(
        "IBAN", [required_for(currency="EUR", providers=["banktransfer"])]
    )
    swiftbic = StringField(
        "SWIFT BIC", [required_for(currency="EUR", providers=["banktransfer"])]
    )
    donation_amount = IntegerRangeField("Donation amount")
    payee_name = StringField(
        "Name of account holder", [required_for(providers=["banktransfer"])]
    )
    note = StringField("Note")
    submit = SubmitField("Request refund")


def wise_validate(endpoint, **args):
    res = requests.get(f"https://api.transferwise.com/v1/validators/{endpoint}", args)
    data = res.json()
    if data.get("validation") != "success":
        app.logger.info(f"Bank validation for {endpoint} failed: {repr(data)}")
        return False

    return True


def validate_bank_details(form, currency):
    app.logger.info("Validating bank details")
    if currency == "GBP":
        if not wise_validate("sort-code", sortCode=form.sort_code.data):
            return False

        if not wise_validate(
            "sort-code-account-number", accountNumber=form.account.data
        ):
            return False

    elif currency == "EUR":
        if not wise_validate("bic", bic=form.swiftbic.data, iban=form.iban.data):
            return False

    app.logger.info("Bank validation succeeded")
    return True


@payments.route("/payment/<int:payment_id>/refund", methods=["GET", "POST"])
@payments.route("/payment/<int:payment_id>/refund/<currency>", methods=["GET", "POST"])
@login_required
def payment_refund_request(payment_id, currency=None):
    if get_refund_state() == "off":
        flash(
            f"Refunds are not currently available. If you need further help please email {app.config['TICKETS_EMAIL'][1]}"
        )
        return redirect(url_for("users.purchases"))

    payment = get_user_payment_or_abort(payment_id, valid_states=["paid"])

    if currency is None:
        currency = payment.currency

    form = RefundRequestForm()
    form._currency = currency
    form._provider = payment.provider
    form._total_amount = payment.amount

    bank_validation_failed = False

    if form.validate_on_submit():
        if (
            payment.provider in {"banktransfer"}
            and payment.amount != form.donation_amount.data
            and not validate_bank_details(form, currency)
        ):

            if payment.currency == "GBP":
                bank_type = "UK"
            else:
                bank_type = "Euro"
            msg = f"Your {bank_type} bank details don't appear to be valid, please check them."
            form.sort_code.errors.append(msg)
            form.account.errors.append(msg)
            form.iban.errors.append(msg)
            form.swiftbic.errors.append(msg)
            bank_validation_failed = True
        else:
            app.logger.info("Creating refund request for payment %s", payment.id)
            req = RefundRequest(
                payment=payment,
                currency=currency,
                donation=form.donation_amount.data,
                sort_code=form.sort_code.data,
                account=form.account.data,
                iban=form.iban.data,
                swiftbic=form.swiftbic.data,
                note=form.note.data,
                payee_name=form.payee_name.data,
            )
            db.session.add(req)
            payment.state = "refund-requested"
            db.session.commit()

            flash(
                "Your refund request has been submitted. We will email you when it's processed."
            )
            return redirect(url_for("users.purchases"))

    return render_template(
        "payments/refund-request.html",
        payment=payment,
        form=form,
        currency=currency,
        bank_validation_failed=bank_validation_failed,
    )
