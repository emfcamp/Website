import requests
from flask import (
    render_template,
    redirect,
    current_app as app,
    flash,
    request,
    url_for,
)
from flask_login import login_required
from wtforms import StringField, SubmitField, FieldList, FormField
from wtforms.validators import ValidationError
from wtforms.fields.html5 import IntegerRangeField

from . import payments
from .common import get_user_payment_or_abort
from ..common.forms import Form, RefundPurchaseForm, update_refund_purchase_form_details
from main import db
from models import RefundRequest
from models.site_state import get_refund_state


@payments.route("/pay/terms")
def terms():
    return render_template("terms.html")


def required_for(currency=None, providers=None):
    def validate(form, field):
        if (
            form.donation_amount.data
            and form._total_amount == form.donation_amount.data
        ):
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

    purchases = FieldList(FormField(RefundPurchaseForm))

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

    payment = get_user_payment_or_abort(
        payment_id, valid_states=["paid", "partrefunded"]
    )

    if not payment.is_refundable or not any(
        [t.is_refundable for t in payment.purchases]
    ):
        flash(
            """Payment cannot be refunded. It is either in an unpaid state or
            has no associated tickets; if you have transferred tickets to
            others please have them transferred back and try again"""
        )
        return redirect(url_for("users.purchases"))

    if currency is None:
        currency = payment.currency

    form = RefundRequestForm()
    form._currency = currency
    form._provider = payment.provider
    form._total_amount = payment.amount

    if request.method != "POST":
        for purchase in payment.purchases:
            form.purchases.append_entry()
            form.purchases[-1].purchase_id.data = purchase.id

    purchases_dict = {p.id: p for p in payment.purchases}

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
            purchases = [
                purchases_dict[f.purchase_id.data]
                for f in form.purchases
                if purchases_dict[f.purchase_id.data].is_refundable and f.refund.data
            ]
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
                purchases=purchases,
            )
            db.session.add(req)
            payment.state = "refund-requested"
            db.session.commit()

            flash(
                "Your refund request has been submitted. We will email you when it's processed."
            )
            return redirect(url_for("users.purchases"))

    for f in form.purchases:
        update_refund_purchase_form_details(f, purchases_dict[f.purchase_id.data])

    if get_refund_state() == "cancellation":
        return render_template(
            "payments/event-cancelled-refund-request.html",
            payment=payment,
            form=form,
            currency=currency,
            bank_validation_failed=bank_validation_failed,
        )

    return render_template(
        "payments/refund-request.html",
        payment=payment,
        form=form,
        currency=currency,
        bank_validation_failed=bank_validation_failed,
    )
