from datetime import datetime, timedelta

from . import admin

from flask import (
    render_template,
    redirect,
    request,
    flash,
    url_for,
    abort,
    current_app as app,
)
from flask.typing import ResponseReturnValue
from flask_login import current_user
from flask_mailman import EmailMessage

from wtforms import SubmitField

from sqlalchemy.sql.functions import func

from main import db, stripe
from models.payment import (
    Payment,
    RefundRequest,
    BankPayment,
    StateException,
)
from models.purchase import Purchase
from ..common.email import from_email
from ..common.forms import Form, RefundForm, RefundFormException
from ..payments.stripe import (
    StripeUpdateUnexpected,
    StripeUpdateConflict,
    stripe_update_payment,
)


@admin.route("/payments")
def payments():
    payments = (
        Payment.query.join(Purchase)
        .with_entities(Payment, func.count(Purchase.id).label("purchase_count"))
        .group_by(Payment)
        .order_by(Payment.id)
        .all()
    )

    return render_template("admin/payments/payments.html", payments=payments)


@admin.route("/payments/expiring")
def expiring():
    expiring = (
        BankPayment.query.join(Purchase)
        .filter(
            BankPayment.state == "inprogress",
            BankPayment.expires < datetime.utcnow() + timedelta(days=3),
        )
        .with_entities(BankPayment, func.count(Purchase.id).label("purchase_count"))
        .group_by(BankPayment)
        .order_by(BankPayment.expires)
        .all()
    )

    return render_template("admin/payments/payments-expiring.html", expiring=expiring)


@admin.route("/payment/<int:payment_id>")
def payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    return render_template("admin/payments/payment.html", payment=payment)


class ResetExpiryForm(Form):
    reset = SubmitField("Reset")


@admin.route("/payment/<int:payment_id>/reset-expiry", methods=["GET", "POST"])
def reset_expiry(payment_id):
    payment = BankPayment.query.get_or_404(payment_id)

    form = ResetExpiryForm()
    if form.validate_on_submit():
        if form.reset.data:
            app.logger.info(
                "%s manually extending expiry for payment %s",
                current_user.name,
                payment.id,
            )

            payment.lock()

            if payment.currency == "GBP":
                days = app.config.get("EXPIRY_DAYS_TRANSFER")
            elif payment.currency == "EUR":
                days = app.config.get("EXPIRY_DAYS_TRANSFER_EURO")

            payment.expires = datetime.utcnow() + timedelta(days=days)
            db.session.commit()

            app.logger.info("Reset expiry by %s days", days)

            flash("Expiry reset for payment %s" % payment.id)
            return redirect(url_for("admin.expiring"))

    return render_template(
        "admin/payments/payment-reset-expiry.html", payment=payment, form=form
    )


class SendReminderForm(Form):
    remind = SubmitField("Send reminder")


@admin.route("/payment/<int:payment_id>/reminder", methods=["GET", "POST"])
def send_reminder(payment_id):
    payment = BankPayment.query.get_or_404(payment_id)

    form = SendReminderForm()
    if form.validate_on_submit():
        if form.remind.data:
            app.logger.info(
                "%s sending reminder email to %s <%s> for payment %s",
                current_user.name,
                payment.user.name,
                payment.user.email,
                payment.id,
            )

            payment.lock()

            if payment.reminder_sent_at:
                app.logger.error("Reminder for payment %s already sent", payment.id)
                flash(
                    "Cannot send duplicate reminder email for payment %s" % payment.id
                )
                return redirect(url_for("admin.expiring"))

            msg = EmailMessage(
                "Electromagnetic Field: Your tickets will expire in five days",
                from_email=from_email("TICKETS_EMAIL"),
                to=[payment.user.email],
            )
            msg.body = render_template(
                "emails/tickets-reminder.txt",
                payment=payment,
                account=payment.recommended_destination,
            )
            msg.send()

            payment.reminder_sent_at = datetime.utcnow()
            db.session.commit()

            flash("Reminder email for payment %s sent" % payment.id)
            return redirect(url_for("admin.expiring"))

    return render_template(
        "admin/payments/payment-send-reminder.html",
        payment=payment,
        account=payment.recommended_destination,
        form=form,
    )


class UpdatePaymentForm(Form):
    update = SubmitField("Update payment")


@admin.route("/payment/<int:payment_id>/update", methods=["GET", "POST"])
def update_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    if payment.provider not in {"stripe"}:
        abort(404)

    form = UpdatePaymentForm()
    if form.validate_on_submit():
        if form.update.data:
            app.logger.info(
                "Requesting updated status for %s payment %s",
                payment.provider,
                payment.id,
            )

            payment.lock()

            if payment.provider == "stripe":
                try:
                    stripe_update_payment(payment)
                except StripeUpdateConflict as e:
                    app.logger.warn(f"StripeUpdateConflict updating payment: {e}")
                    flash("Unable to update due to a status conflict")
                    return redirect(
                        url_for("admin.update_payment", payment_id=payment.id)
                    )
                except StripeUpdateUnexpected as e:
                    app.logger.warn(f"StripeUpdateUnexpected updating payment: {e}")
                    flash("Unable to update due to an unexpected response from Stripe")
                    return redirect(
                        url_for("admin.update_payment", payment_id=payment.id)
                    )

            flash("Payment status updated")
            return redirect(url_for("admin.update_payment", payment_id=payment.id))

    return render_template(
        "admin/payments/payment-update.html", payment=payment, form=form
    )


class CancelPaymentForm(Form):
    cancel = SubmitField("Cancel payment")


@admin.route("/payment/<int:payment_id>/cancel", methods=["GET", "POST"])
def cancel_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    if payment.provider == "stripe":
        msg = "Cannot cancel stripe payment (id: %s)." % payment_id
        app.logger.warn(msg)
        flash(msg)
        return redirect(url_for("admin.payments"))

    form = CancelPaymentForm()
    if form.validate_on_submit():
        if form.cancel.data and (payment.provider in {"banktransfer"}):
            app.logger.info(
                "%s manually cancelling payment %s", current_user.name, payment.id
            )

            payment.lock()

            try:
                payment.cancel()
            except StateException as e:
                msg = "Could not cancel payment %s: %s" % (payment_id, e)
                app.logger.warn(msg)
                flash(msg)
                return redirect(url_for("admin.payments"))

            db.session.commit()

            flash("Payment %s cancelled" % payment.id)
            return redirect(url_for("admin.expiring"))

    return render_template(
        "admin/payments/payment-cancel.html", payment=payment, form=form
    )


@admin.route("/payment/requested-refunds")
def requested_refunds():
    state = request.args.get("state", "refund-requested")
    requests = (
        RefundRequest.query.join(Payment)
        .join(Purchase)
        .filter(Payment.state == state)
        .with_entities(RefundRequest, func.count(Purchase.id).label("purchase_count"))
        .order_by(RefundRequest.id)
        .group_by(RefundRequest.id, Payment.id)
        .all()
    )

    return render_template(
        "admin/payments/requested_refunds.html", requests=requests, state=state
    )


class DeleteRefundRequestForm(Form):
    refund = SubmitField("Delete refund request")


@admin.route("/payment/requested-refunds/<int:req_id>/delete", methods=["GET", "POST"])
def delete_refund_request(req_id):
    """Delete a refund request. This can only be called if the payment is in the
    refund-requested state, or if it's "refunded" but with a 100% donation."""
    req = RefundRequest.query.get_or_404(req_id)

    # TODO: this does not handle partial refunds!
    # It can also fail if there's insufficient capacity to return the ticket state.
    if not (
        req.payment.state == "refund-requested"
        or (req.payment.state == "refunded" and req.donation == req.payment.amount)
    ):
        return abort(400)

    form = DeleteRefundRequestForm()
    if form.validate_on_submit():
        for purchase in req.payment.purchases:
            if purchase.state == "refunded":
                purchase.un_refund()

        req.payment.state = "paid"
        db.session.delete(req)
        db.session.commit()

        flash("Refund request deleted")
        return redirect(url_for(".requested_refunds"))

    return render_template(
        "admin/payments/refund_request_delete.html", req=req, form=form
    )


class ManualRefundForm(Form):
    refund = SubmitField("Refund payment")


@admin.route("/payment/<int:payment_id>/manual-refund", methods=["GET", "POST"])
def manual_refund(payment_id):
    """Mark an entire payment as refunded for book-keeping purposes.
    Doesn't actually take any steps to return money to the user."""

    # TODO: this is old! We should move manual refund handling to the other refund endpoint for consistency.

    payment = Payment.query.get_or_404(payment_id)

    if payment.refund_requests:
        app.logger.warn("Showing refund requests for payment %s", payment.id)

    form = ManualRefundForm()
    if form.validate_on_submit():
        if form.refund.data:
            app.logger.info("Manually refunding payment %s", payment.id)

            payment.lock()

            try:
                payment.manual_refund()

            except StateException as e:
                app.logger.warn("Could not refund payment %s: %s", payment_id, e)
                flash("Could not refund payment due to a state error")
                return redirect(url_for("admin.payments"))

            db.session.commit()

            flash("Payment {} refunded".format(payment.id))
            return redirect(url_for("admin.payments"))

    return render_template(
        "admin/payments/manual-refund.html", payment=payment, form=form
    )


@admin.route("/payment/<int:payment_id>/refund", methods=["GET", "POST"])
def refund(payment_id):
    # TODO: This is all old and needs fixing
    # For partial refunds, we need to let *users* select which tickets they want to refund (see ticket #900)
    # Refund business logic needs moving to apps.payments.refund module, some is already there.
    payment = Payment.query.get_or_404(payment_id)

    if not payment.is_refundable:
        app.logger.warning(
            "Cannot refund payment %s is %s, not in valid state",
            payment_id,
            payment.state,
        )
        flash("Payment is not currently refundable")
        return redirect(url_for(".payments"))

    form = RefundForm(request.form)

    form.intialise_with_payment(payment, set_purchase_ids=(request.method != "POST"))

    if form.validate_on_submit():
        if form.refund.data or form.stripe_refund.data:
            try:
                total_refunded = form.process_refund(payment, db, app.logger, stripe)
            except RefundFormException as e:
                flash(e)
                return redirect(url_for(".refund", payment_id=payment.id))

            app.logger.info(
                "Payment %s refund complete for a total of %s",
                payment.id,
                total_refunded,
            )
            flash("Refund for %s %s complete" % (total_refunded, payment.currency))

        return redirect(url_for(".requested_refunds"))

    refunded_purchases = [p for p in payment.purchases if p.state == "refunded"]
    return render_template(
        "admin/payments/refund.html",
        payment=payment,
        form=form,
        refunded_purchases=refunded_purchases,
    )


class ChangeCurrencyForm(Form):
    change = SubmitField("Change Currency")


@admin.route("/payment/<int:payment_id>/change_currency", methods=["GET", "POST"])
def change_currency(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    if not (
        payment.state == "new"
        or (payment.provider == "banktransfer" and payment.state == "inprogress")
    ):
        return abort(400)

    if payment.currency == "GBP":
        new_currency = "EUR"
    else:
        new_currency = "GBP"

    form = ChangeCurrencyForm(request.form)
    if form.validate_on_submit():
        payment.change_currency(new_currency)
        db.session.commit()
        flash(f"Currency successfully changed to {new_currency}")
        return redirect(url_for(".payment", payment_id=payment.id))

    return render_template(
        "admin/payments/change-currency.html",
        payment=payment,
        form=form,
        new_currency=new_currency,
    )


class CancelPurchaseForm(Form):
    cancel = SubmitField("Cancel purchase")


@admin.route(
    "/payment/<int:payment_id>/cancel_purchase/<int:purchase_id>",
    methods=["GET", "POST"],
)
def cancel_purchase(payment_id: int, purchase_id: int) -> ResponseReturnValue:
    """Remove a purchase from a payment before it has been paid.

    This is used when the purchaser changes their mind before they've sent us the money.
    """
    payment: Payment = Payment.query.get_or_404(payment_id)
    purchase: Purchase = Purchase.query.get_or_404(purchase_id)

    if purchase.payment != payment:
        return abort(400)

    if purchase.state != "payment-pending":
        return abort(400)

    form = CancelPurchaseForm()
    if form.validate_on_submit():
        if form.cancel.data:
            app.logger.info(
                "%s manually cancelling purchase %s", current_user.name, purchase.id
            )
            payment.lock()

            try:
                purchase.cancel()
            except StateException as e:
                msg = "Could not cancel purchase %s: %s" % (purchase_id, e)
                app.logger.warn(msg)
                flash(msg)
                return redirect(url_for("admin.payment", payment_id=payment.id))

            purchase.payment_id = None
            payment.amount -= purchase.price_tier.get_price(payment.currency).value

            db.session.commit()

            flash("Purchase %s cancelled" % purchase.id)
            return redirect(url_for("admin.payment", payment_id=payment.id))

    return render_template(
        "admin/payments/purchase-cancel.html",
        payment=payment,
        purchase=purchase,
        form=form,
    )
