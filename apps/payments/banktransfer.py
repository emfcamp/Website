from datetime import datetime, timedelta
import logging

from flask import render_template, redirect, flash, url_for, current_app as app
from flask_login import login_required, current_user
from flask_mailman import EmailMessage
from wtforms import SubmitField, HiddenField
from wtforms.validators import DataRequired, AnyOf

from main import db
from models.payment import BankPayment, BankTransaction
from ..common import get_user_currency, feature_enabled
from ..common.email import from_email
from ..common.forms import Form
from ..common.receipt import attach_tickets, set_tickets_emailed
from . import get_user_payment_or_abort, lock_user_payment_or_abort
from . import payments

logger = logging.getLogger(__name__)


def transfer_start(payment: BankPayment):
    if not feature_enabled("BANK_TRANSFER"):
        return redirect(url_for("tickets.pay"))

    if get_user_currency() == "EUR" and not feature_enabled("BANK_TRANSFER_EURO"):
        return redirect(url_for("tickets.pay"))

    logger.info("Created bank payment %s (%s)", payment.id, payment.bankref)

    # No extra preparation required for bank transfer. We can go straight to inprogress.

    if payment.currency == "GBP":
        days = app.config.get("EXPIRY_DAYS_TRANSFER")
    elif payment.currency == "EUR":
        days = app.config.get("EXPIRY_DAYS_TRANSFER_EURO")

    if days is None:
        raise Exception("EXPIRY_DAYS_TRANSFER(_EURO) not set")

    payment.expires = datetime.utcnow() + timedelta(days=days)
    payment.state = "inprogress"

    for purchase in payment.purchases:
        purchase.set_state("payment-pending")

    db.session.commit()

    msg = EmailMessage(
        "Your EMF ticket purchase",
        from_email=from_email("TICKETS_EMAIL"),
        to=[current_user.email],
    )
    msg.body = render_template(
        "emails/tickets-purchased-email-banktransfer.txt",
        user=current_user,
        payment=payment,
    )
    msg.send()

    return redirect(url_for("payments.transfer_waiting", payment_id=payment.id))


class TransferChangeCurrencyForm(Form):
    currency = HiddenField("New currency", [DataRequired(), AnyOf(["EUR", "GBP"])])
    change = SubmitField("Change currency")


@payments.route("/pay/transfer/<int:payment_id>/waiting")
@login_required
def transfer_waiting(payment_id):
    form = TransferChangeCurrencyForm()

    payment = get_user_payment_or_abort(
        payment_id, "banktransfer", valid_states=["inprogress", "paid"]
    )

    if payment.currency == "GBP":
        form.currency.data = "EUR"
    elif payment.currency == "EUR":
        form.currency.data = "GBP"

    return render_template(
        "payments/transfer-waiting.html",
        payment=payment,
        account=payment.recommended_destination,
        form=form,
        days=app.config["EXPIRY_DAYS_TRANSFER"],
    )


@payments.route("/pay/transfer/<int:payment_id>/change-currency", methods=["POST"])
@login_required
def transfer_change_currency(payment_id):
    payment = lock_user_payment_or_abort(
        payment_id, "banktransfer", valid_states=["inprogress"]
    )

    form = TransferChangeCurrencyForm()
    if form.validate_on_submit():
        if form.change.data:
            logger.info("Changing currency for bank transfer %s", payment.id)

            currency = form.currency.data

            if currency == payment.currency:
                flash("Currency is already {}".format(currency))
                return redirect(
                    url_for("payments.transfer_waiting", payment_id=payment.id)
                )

            payment.change_currency(currency)
            db.session.commit()

            logger.info("Payment %s changed to %s", payment.id, currency)
            flash("Currency changed to {}".format(currency))

        return redirect(url_for("payments.transfer_waiting", payment_id=payment.id))

    return redirect(url_for("payments.transfer_waiting", payment_id=payment.id))


class TransferCancelForm(Form):
    yes = SubmitField("Cancel transfer")


@payments.route("/pay/transfer/<int:payment_id>/cancel", methods=["GET", "POST"])
@login_required
def transfer_cancel(payment_id):
    payment = lock_user_payment_or_abort(
        payment_id, "banktransfer", valid_states=["new", "inprogress", "cancelled"]
    )

    if payment.state == "cancelled":
        logger.info("Payment %s has already been cancelled", payment.id)
        flash("Payment has already been cancelled")
        return redirect(url_for("users.purchases"))

    form = TransferCancelForm()
    if form.validate_on_submit():
        if form.yes.data:
            logger.info("Cancelling bank transfer %s", payment.id)
            payment.cancel()
            db.session.commit()

            logger.info("Payment %s cancelled", payment.id)
            flash("Payment cancelled")

        return redirect(url_for("users.purchases"))

    return render_template("payments/transfer-cancel.html", payment=payment, form=form)


def reconcile_txns(txns: list[BankTransaction], doit: bool = False):
    paid = 0
    failed = 0

    for txn in txns:
        if txn.type.lower() not in ("other", "directdep", "deposit"):
            raise ValueError("Unexpected transaction type for %s: %s", txn.id, txn.type)

        # TODO: remove this after 2022
        if txn.payee.startswith("GOCARDLESS ") or txn.payee.startswith("GC C1 EMF"):
            app.logger.info("Suppressing GoCardless transfer %s", txn.id)
            if doit:
                txn.suppressed = True
                db.session.commit()
            continue

        if txn.payee.startswith("STRIPE PAYMENTS EU ") or txn.payee.startswith(
            "STRIPE STRIPE"
        ):
            app.logger.info("Suppressing Stripe transfer %s", txn.id)
            if doit:
                txn.suppressed = True
                db.session.commit()
            continue

        app.logger.info("Processing txn %s: %s", txn.id, txn.payee)

        payment = txn.match_payment()
        if not payment:
            app.logger.warn("Could not match payee, skipping")
            failed += 1
            continue

        app.logger.info(
            "Matched to payment %s by %s for %s %s",
            payment.id,
            payment.user.name,
            payment.amount,
            payment.currency,
        )

        if doit:
            payment.lock()

        if txn.amount != payment.amount:
            app.logger.warn(
                "Transaction amount %s doesn't match %s, skipping",
                txn.amount,
                payment.amount,
            )
            failed += 1
            db.session.rollback()
            continue

        if txn.account.currency != payment.currency:
            app.logger.warn(
                "Transaction currency %s doesn't match %s, skipping",
                txn.account.currency,
                payment.currency,
            )
            failed += 1
            db.session.rollback()
            continue

        if payment.state == "paid":
            app.logger.error("Payment %s has already been paid", payment.id)
            failed += 1
            db.session.rollback()
            continue

        if doit:
            txn.payment = payment
            payment.paid()

            send_confirmation(payment)

            db.session.commit()

        app.logger.info("Payment reconciled")
        paid += 1

    app.logger.info("Reconciliation complete: %s paid, %s failed", paid, failed)


def send_confirmation(payment: BankPayment):
    msg = EmailMessage(
        "Electromagnetic Field ticket purchase update",
        from_email=from_email("TICKETS_EMAIL"),
        to=[payment.user.email],
    )

    already_emailed = set_tickets_emailed(payment.user)
    msg.body = render_template(
        "emails/tickets-paid-email-banktransfer.txt",
        user=payment.user,
        payment=payment,
        already_emailed=already_emailed,
    )

    if feature_enabled("ISSUE_TICKETS"):
        attach_tickets(msg, payment.user)

    msg.send()
    db.session.commit()
