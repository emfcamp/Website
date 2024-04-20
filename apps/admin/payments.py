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

from wtforms.validators import InputRequired
from wtforms import SubmitField, BooleanField, FieldList, FormField

from sqlalchemy.sql.functions import func

from main import db, stripe
from models.payment import (
    Payment,
    RefundRequest,
    BankPayment,
    BankRefund,
    StripeRefund,
    StateException,
)
from models.purchase import AdmissionTicket, Purchase
from ..common.email import from_email
from ..common.forms import Form
from ..common.fields import HiddenIntegerField
from ..payments.stripe import (
    StripeUpdateUnexpected,
    StripeUpdateConflict,
    stripe_update_payment,
    stripe_payment_refunded,
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


class RefundPurchaseForm(Form):
    purchase_id = HiddenIntegerField("Purchase ID", [InputRequired()])
    refund = BooleanField("Refund purchase", default=True)


class RefundForm(Form):
    purchases = FieldList(FormField(RefundPurchaseForm))
    refund = SubmitField("I have refunded these purchases by bank transfer")
    stripe_refund = SubmitField("Refund through Stripe")


@admin.route("/payment/<int:payment_id>/refund", methods=["GET", "POST"])
def refund(payment_id):
    # TODO: This is all old and needs fixing
    # For partial refunds, we need to let *users* select which tickets they want to refund (see ticket #900)
    # Refund business logic needs moving to apps.payments.refund module, some is already there.
    payment = Payment.query.get_or_404(payment_id)

    if not payment.is_refundable(override_refund_state_machine=True):
        app.logger.warning(
            "Payment %s is %s, which is not a refundable state",
            payment_id,
            payment.state,
        )
        flash("Payment is not currently refundable")
        return redirect(url_for(".payments"))

    form = RefundForm(request.form)

    if payment.provider != "stripe":
        # Make sure the stripe_refund submit won't count as pressed
        form.stripe_refund.data = ""

    if request.method != "POST":
        for purchase in payment.purchases:
            form.purchases.append_entry()
            form.purchases[-1].purchase_id.data = purchase.id

    purchases_dict = {p.id: p for p in payment.purchases}

    for f in form.purchases:
        f._purchase = purchases_dict[f.purchase_id.data]
        f.refund.label.text = "%s - %s" % (
            f._purchase.id,
            f._purchase.product.display_name,
        )

        if (
            f._purchase.refund_id is None
            and f._purchase.is_paid_for
            and f._purchase.owner == payment.user
        ):
            # Purchase is owned by the user and not already refunded
            f._disabled = False

            if type(f._purchase) == AdmissionTicket and f._purchase.checked_in:
                f.refund.data = False
                f.refund.label.text += " (checked in)"
        elif f._purchase.refund_id is not None:
            f._disabled = True
            f.refund.data = False
            f.refund.label.text += " (refunded)"
        else:
            f._disabled = True
            f.refund.data = False
            f.refund.label.text += " (transferred)"

    if form.validate_on_submit():
        if form.refund.data or form.stripe_refund.data:

            payment.lock()

            purchases = [
                f._purchase for f in form.purchases if f.refund.data and not f._disabled
            ]
            total = sum(
                p.price_tier.get_price(payment.currency).value for p in purchases
            )

            if not total:
                flash(
                    "Please select some purchases to refund. You cannot refund only free purchases from this page."
                )
                return redirect(url_for(".refund", payment_id=payment.id))

            if any(p.owner != payment.user for p in purchases):
                flash("Cannot refund transferred purchase")
                return redirect(url_for(".refund", payment_id=payment.id))

            # This is where you'd add the premium if it existed
            app.logger.info(
                "Refunding %s purchases from payment %s, totalling %s %s",
                len(purchases),
                payment.id,
                total,
                payment.currency,
            )

            if form.stripe_refund.data:
                app.logger.info("Refunding using Stripe")
                charge = stripe.Charge.retrieve(payment.charge_id)

                if charge.refunded:
                    # This happened unexpectedly - send the email as usual
                    stripe_payment_refunded(payment)
                    flash("This charge has already been fully refunded.")
                    return redirect(url_for(".refund", payment_id=payment.id))

                payment.state = "refunding"
                refund = StripeRefund(payment, total)

            else:
                app.logger.info("Refunding out of band")

                payment.state = "refunding"
                refund = BankRefund(payment, total)

            with db.session.no_autoflush:
                for purchase in purchases:
                    purchase.refund_purchase(refund)

            priced_purchases = [
                p
                for p in payment.purchases
                if p.price_tier.get_price(payment.currency).value
            ]
            unpriced_purchases = [
                p
                for p in payment.purchases
                if not p.price_tier.get_price(payment.currency).value
            ]

            all_refunded = False
            if all(p.refund for p in priced_purchases):
                all_refunded = True
                # Remove remaining free purchases from the payment so they're still valid.
                for purchase in unpriced_purchases:
                    if not purchase.refund:
                        app.logger.info(
                            "Removing free purchase %s from refunded payment",
                            purchase.id,
                        )
                        if not purchase.is_paid_for:
                            # The only thing keeping this purchase from being valid was the payment
                            app.logger.info(
                                "Setting orphaned free purchase %s to paid", purchase.id
                            )
                            purchase.state = "paid"

                            # Should we even put free purchases in a Payment?

                        purchase.payment = None
                        purchase.payment_id = None

            db.session.commit()

            if form.stripe_refund.data:
                try:
                    stripe_refund = stripe.Refund.create(
                        charge=payment.charge_id, amount=refund.amount_int
                    )

                except Exception as e:
                    app.logger.exception("Exception %r refunding payment", e)
                    flash(
                        "An error occurred refunding with Stripe. Please check the state of the payment."
                    )
                    return redirect(url_for(".refund", payment_id=payment.id))

                refund.refundid = stripe_refund.id
                if stripe_refund.status not in ("pending", "succeeded"):
                    # Should never happen according to the docs
                    app.logger.warn(
                        "Refund status is %s, not pending or succeeded",
                        stripe_refund.status,
                    )
                    flash(
                        "The refund with Stripe was not successful. Please check the state of the payment."
                    )
                    return redirect(url_for(".refund", payment_id=payment.id))

            if all_refunded:
                payment.state = "refunded"
            else:
                payment.state = "partrefunded"

            db.session.commit()

            app.logger.info(
                "Payment %s refund complete for a total of %s", payment.id, total
            )
            flash("Refund for %s %s complete" % (total, payment.currency))

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
