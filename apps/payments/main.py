import requests
from flask import render_template, redirect, flash, url_for, current_app as app
from flask_login import login_required
from wtforms import StringField, SubmitField
from wtforms.validators import ValidationError
from wtforms.fields.html5 import IntegerRangeField
import gocardless_pro.errors

from . import payments
from .common import get_user_payment_or_abort
from ..common import feature_flag
from ..common.forms import Form
from main import db, gocardless_client
from models import RefundRequest


@payments.route("/pay/terms")
def terms():
    return render_template("terms.html")


def required_for(currency=None, providers=None):
    def validate(form, field):
        if providers is not None and form._provider not in providers:
            return
        if currency is not None and form._currency != currency:
            return
        if not field.data:
            raise ValidationError("This field is required")

    return validate


class RefundRequestForm(Form):
    # https://developer.gocardless.com/api-reference/#appendix-local-bank-details
    # We only support UK and international (Euros)
    sort_code = StringField(
        "Sort code",
        [required_for(currency="GBP", providers=["banktransfer", "gocardless"])],
    )
    account = StringField(
        "Account number",
        [required_for(currency="GBP", providers=["banktransfer", "gocardless"])],
    )
    iban = StringField(
        "IBAN", [required_for(currency="EUR", providers=["banktransfer", "gocardless"])]
    )
    swiftbic = StringField(
        "SWIFT BIC",
        [required_for(currency="EUR", providers=["banktransfer", "gocardless"])],
    )
    donation_amount = IntegerRangeField("Donation amount")
    payee_name = StringField(
        "Name of account holder",
        [required_for(providers=["banktransfer", "gocardless"])],
    )
    note = StringField("Note")
    submit = SubmitField("Request refund")
    really_submit = SubmitField("These details are correct")


def validate_bank_details(form, currency):
    """ Transferwise can't validate sort code and account number.
        GoCardless can't validate BIC and IBAN.
        Use both.
    """
    app.logger.info("Validating bank details")
    if currency == "GBP":
        params = {
            "country_code": "GB",
            "branch_code": form.sort_code.data,
            "account_number": form.account.data,
        }
        try:
            result = gocardless_client.bank_details_lookups.create(params)
            app.logger.info(
                "GBP bank identified as %r", result.attributes.get("bank_name")
            )
        except gocardless_pro.errors.ValidationFailedError as e:
            app.logger.warn("Error validating GBP bank details: %s", e)
            return False
    elif currency == "EUR":
        params = {"iban": form.iban.data}
        res = requests.get(
            "https://api.transferwise.com/v1/validators/bic?"
            f"bic={form.swiftbic.data}&iban={form.iban.data}"
        )

        result = res.json()
        if result.get("validation") != "success":
            return False

    app.logger.info("Bank validation succeeded")
    return True


@payments.route("/payment/<int:payment_id>/refund", methods=["GET", "POST"])
@payments.route("/payment/<int:payment_id>/refund/<currency>", methods=["GET", "POST"])
@login_required
@feature_flag("REFUND_REQUESTS")
def payment_refund_request(payment_id, currency=None):
    payment = get_user_payment_or_abort(payment_id, valid_states=["paid"])
    if currency is None:
        currency = payment.currency

    form = RefundRequestForm()
    form._currency = currency
    form._provider = payment.provider

    bank_validation_failed = False

    if form.validate_on_submit():
        if (
            payment.provider in ("banktransfer", "gocardless")
            and not form.really_submit.data
            and not validate_bank_details(form, currency)
        ):
            msg = (
                "Your bank details don't appear to be valid, please check them. "
                "Please submit the form again if you're sure they're correct."
            )
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

            flash("Your refund request has been sent")
            return redirect(url_for("users.purchases"))

    return render_template(
        "payments/refund-request.html",
        payment=payment,
        form=form,
        currency=currency,
        bank_validation_failed=bank_validation_failed,
    )
