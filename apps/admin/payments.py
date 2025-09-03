from datetime import timedelta
from typing import assert_never

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask import (
    current_app as app,
)
from flask.typing import ResponseReturnValue
from flask_login import current_user
from flask_mailman import EmailMessage
from sqlalchemy.sql.functions import func
from wtforms import FieldList, FormField, SubmitField

from main import db, get_or_404, get_stripe_client
from models import Currency, naive_utcnow
from models.payment import (
    BankPayment,
    BankRefund,
    Payment,
    RefundRequest,
    StateException,
    StripeRefund,
)
from models.product import Price
from models.purchase import Purchase

from ..common.email import from_email
from ..common.forms import Form, RefundPurchaseForm, update_refund_purchase_form_details
from ..payments.stripe import (
    StripeUpdateConflict,
    StripeUpdateUnexpected,
    stripe_payment_refunded,
    stripe_update_payment,
)
from . import admin


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
            BankPayment.expires < naive_utcnow() + timedelta(days=3),
        )
        .with_entities(BankPayment, func.count(Purchase.id).label("purchase_count"))
        .group_by(BankPayment)
        .order_by(BankPayment.expires)
        .all()
    )

    return render_template("admin/payments/payments-expiring.html", expiring=expiring)


@admin.route("/payment/<int:payment_id>")
def payment(payment_id):
    payment = get_or_404(db, Payment, payment_id)

    return render_template("admin/payments/payment.html", payment=payment)


class ResetExpiryForm(Form):
    reset = SubmitField("Reset")


@admin.route("/payment/<int:payment_id>/reset-expiry", methods=["GET", "POST"])
def reset_expiry(payment_id) -> ResponseReturnValue:
    payment = get_or_404(db, BankPayment, payment_id)

    form = ResetExpiryForm()
    if form.validate_on_submit():
        if form.reset.data:
            app.logger.info(
                "%s manually extending expiry for payment %s",
                current_user.name,
                payment.id,
            )

            payment.lock()

            match payment.currency:
                case Currency.GBP:
                    days = app.config.get("EXPIRY_DAYS_TRANSFER")
                case Currency.EUR:
                    days = app.config.get("EXPIRY_DAYS_TRANSFER_EURO")
                case _:
                    assert_never(payment.currency)

            if not isinstance(days, int):
                raise Exception("EXPIRY_DAYS_TRANSFER(_EURO) not an int")

            payment.expires = naive_utcnow() + timedelta(days=days)
            db.session.commit()

            app.logger.info("Reset expiry to %s days from now", days)

            flash(f"Expiry reset for payment {payment.id}")
            return redirect(url_for("admin.expiring"))

    return render_template("admin/payments/payment-reset-expiry.html", payment=payment, form=form)


class SendReminderForm(Form):
    remind = SubmitField("Send reminder")


@admin.route("/payment/<int:payment_id>/reminder", methods=["GET", "POST"])
def send_reminder(payment_id):
    payment = get_or_404(db, BankPayment, payment_id)

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
                flash(f"Cannot send duplicate reminder email for payment {payment.id}")
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

            payment.reminder_sent_at = naive_utcnow()
            db.session.commit()

            flash(f"Reminder email for payment {payment.id} sent")
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
    payment = get_or_404(db, Payment, payment_id)

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
                stripe_client = get_stripe_client(app.config)
                try:
                    stripe_update_payment(stripe_client, payment)
                except StripeUpdateConflict as e:
                    app.logger.warning(f"StripeUpdateConflict updating payment: {e}")
                    flash("Unable to update due to a status conflict")
                    return redirect(url_for("admin.update_payment", payment_id=payment.id))
                except StripeUpdateUnexpected as e:
                    app.logger.warning(f"StripeUpdateUnexpected updating payment: {e}")
                    flash("Unable to update due to an unexpected response from Stripe")
                    return redirect(url_for("admin.update_payment", payment_id=payment.id))

            flash("Payment status updated")
            return redirect(url_for("admin.update_payment", payment_id=payment.id))

    return render_template("admin/payments/payment-update.html", payment=payment, form=form)


class CancelPaymentForm(Form):
    cancel = SubmitField("Cancel payment")


@admin.route("/payment/<int:payment_id>/cancel", methods=["GET", "POST"])
def cancel_payment(payment_id):
    payment = get_or_404(db, Payment, payment_id)

    if payment.provider == "stripe":
        msg = f"Cannot cancel stripe payment (id: {payment_id})."
        app.logger.warning(msg)
        flash(msg)
        return redirect(url_for("admin.payments"))

    form = CancelPaymentForm()
    if form.validate_on_submit():
        if form.cancel.data and (payment.provider in {"banktransfer"}):
            app.logger.info("%s manually cancelling payment %s", current_user.name, payment.id)

            payment.lock()

            try:
                payment.cancel()
            except StateException as e:
                msg = f"Could not cancel payment {payment_id}: {e}"
                app.logger.warning(msg)
                flash(msg)
                return redirect(url_for("admin.payments"))

            db.session.commit()

            flash(f"Payment {payment.id} cancelled")
            return redirect(url_for("admin.expiring"))

    return render_template("admin/payments/payment-cancel.html", payment=payment, form=form)


@admin.route("/payment/refunds")
@admin.route("/payment/refunds/<view>")
def refunds(view="requested"):
    if view not in {"requested", "resolved"}:
        abort(404)

    if view == "requested":
        query = (
            RefundRequest.query.join(Payment)
            .join(RefundRequest.purchases)
            .join(Purchase.price)
            .filter(Payment.state == "refund-requested")
            .filter(Purchase.state != "refunded")
            .with_entities(
                RefundRequest,
                func.count(Purchase.id).label("purchase_count"),
                func.sum(Price.price_int / 100).label("refund_total"),
            )
            .order_by(RefundRequest.id)
            .group_by(RefundRequest.id, Payment.id)
        )
    else:
        # The resolved refunds don't necessarily tie into the requests.
        # Just show the payments that have been touched by the process.
        refunds = (
            RefundRequest.query.join(Payment)
            .with_entities(
                Payment.id.label("payment_id"),
                func.min(RefundRequest.id).label("req_id"),
            )
            .group_by(Payment.id)
            .subquery()
        )

        query = (
            db.session.query(refunds)
            .join(Payment, Payment.id == refunds.c.payment_id)
            .join(RefundRequest, RefundRequest.id == refunds.c.req_id)
            .join(Payment.purchases)
            .join(Purchase.price)
            .filter(Purchase.state == "refunded")
            .with_entities(
                RefundRequest,
                func.count(Purchase.id).label("purchase_count"),
                func.sum(Price.price_int / 100).label("refund_total"),
            )
            .group_by(RefundRequest)
            .order_by(RefundRequest.id)
        )

    return render_template("admin/payments/refunds.html", query=query.all(), view=view)


class DeleteRefundRequestForm(Form):
    refund = SubmitField("Delete refund request")


@admin.route("/payment/requested-refunds/<int:req_id>/delete", methods=["GET", "POST"])
def delete_refund_request(req_id):
    """Delete a refund request. This can only be called if the payment is in the
    refund-requested state, or if it's "refunded" but with a 100% donation."""
    req = get_or_404(db, RefundRequest, req_id)

    # TODO: this does not handle partial refunds!
    # It can also fail if there's insufficient capacity to return the ticket state.
    if not all(u.state == "paid" for u in req.payment.purchases):
        return abort(400)

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
        return redirect(url_for(".refunds"))

    return render_template("admin/payments/refund_request_delete.html", req=req, form=form)


class ManualRefundForm(Form):
    refund = SubmitField("Refund payment")


@admin.route("/payment/<int:payment_id>/manual-refund", methods=["GET", "POST"])
def manual_refund(payment_id):
    """Mark an entire payment as refunded for book-keeping purposes.
    Doesn't actually take any steps to return money to the user."""

    # TODO: this is old! We should move manual refund handling to the other refund endpoint for consistency.

    payment = get_or_404(db, Payment, payment_id)

    if payment.refund_requests:
        app.logger.warning("Showing refund requests for payment %s", payment.id)

    form = ManualRefundForm()
    if form.validate_on_submit():
        if form.refund.data:
            app.logger.info("Manually refunding payment %s", payment.id)

            payment.lock()

            try:
                payment.manual_refund()

            except StateException as e:
                app.logger.warning("Could not refund payment %s: %s", payment_id, e)
                flash("Could not refund payment due to a state error")
                return redirect(url_for("admin.payments"))

            db.session.commit()

            flash(f"Payment {payment.id} refunded")
            return redirect(url_for("admin.payments"))

    return render_template("admin/payments/manual-refund.html", payment=payment, form=form)


class RefundForm(Form):
    purchases = FieldList(FormField(RefundPurchaseForm))
    refund = SubmitField("I have refunded these purchases by bank transfer")
    stripe_refund = SubmitField("Refund through Stripe")


@admin.route("/payment/<int:payment_id>/refund", methods=["GET", "POST"])
def refund(payment_id):
    # TODO: This is all old and needs fixing
    # For partial refunds, we need to let *users* select which tickets they want to refund (see ticket #900)
    # Refund business logic needs moving to apps.payments.refund module, some is already there.
    payment = get_or_404(db, Payment, payment_id)

    if not payment.is_refundable(ignore_event_refund_state=True):
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

    if form.validate_on_submit():
        if form.refund.data or form.stripe_refund.data:
            payment.lock()

            purchases = [
                purchases_dict[f.purchase_id.data]
                for f in form.purchases
                if f.refund.data
                and purchases_dict[f.purchase_id.data].is_refundable(ignore_event_refund_state=True)
            ]

            total = sum(p.price_tier.get_price(payment.currency).value for p in purchases)

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

            stripe_client = get_stripe_client(app.config)

            if form.stripe_refund.data:
                app.logger.info("Refunding using Stripe")
                charge = stripe_client.charges.retrieve(payment.charge_id)

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
                p for p in payment.purchases if p.price_tier.get_price(payment.currency).value
            ]
            unpriced_purchases = [
                p for p in payment.purchases if not p.price_tier.get_price(payment.currency).value
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
                            app.logger.info("Setting orphaned free purchase %s to paid", purchase.id)
                            purchase.state = "paid"

                            # Should we even put free purchases in a Payment?

                        purchase.payment = None
                        purchase.payment_id = None

            db.session.commit()

            if form.stripe_refund.data:
                try:
                    stripe_refund = stripe_client.refunds.create(
                        params={
                            "charge": payment.charge_id,
                            "amount": refund.amount_int,
                        }
                    )

                except Exception as e:
                    app.logger.exception("Exception %r refunding payment", e)
                    flash("An error occurred refunding with Stripe. Please check the state of the payment.")
                    return redirect(url_for(".refund", payment_id=payment.id))

                refund.refundid = stripe_refund.id
                if stripe_refund.status not in ("pending", "succeeded"):
                    # Should never happen according to the docs
                    app.logger.warning(
                        "Refund status is %s, not pending or succeeded",
                        stripe_refund.status,
                    )
                    flash("The refund with Stripe was not successful. Please check the state of the payment.")
                    return redirect(url_for(".refund", payment_id=payment.id))

            if all_refunded:
                payment.state = "refunded"
            else:
                payment.state = "partrefunded"

            db.session.commit()

            msg = EmailMessage(
                "Your refund from Electromagnetic Field has been processed",
                from_email=from_email("TICKETS_EMAIL"),
                to=[payment.user.email],
            )

            msg.body = render_template(
                "emails/purchase-refund.txt",
                user=payment.user,
                refund_total=total,
                currency=payment.currency,
                purchases=purchases,
                is_stripe=form.stripe_refund.data,
            )
            msg.send()

            app.logger.info("Payment %s refund complete for a total of %s", payment.id, total)
            flash(f"Refund for {total} {payment.currency} complete")

        return redirect(url_for(".refunds"))

    for f in form.purchases:
        purchase = purchases_dict[f.purchase_id.data]
        update_refund_purchase_form_details(f, purchase, ignore_event_refund_state=True)
        if purchase.refund_request and not purchase.refund:
            f.refund.data = True

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
    payment = get_or_404(db, Payment, payment_id)
    if not (payment.state == "new" or (payment.provider == "banktransfer" and payment.state == "inprogress")):
        return abort(400)

    match payment.currency:
        case Currency.GBP:
            new_currency = Currency.EUR
        case Currency.EUR:
            new_currency = Currency.GBP
        case _:
            assert_never(payment.currency)

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
    payment = get_or_404(db, Payment, payment_id)
    purchase = get_or_404(db, Purchase, purchase_id)

    if purchase.payment != payment:
        return abort(400)

    if purchase.state != "payment-pending":
        return abort(400)

    form = CancelPurchaseForm()
    if form.validate_on_submit():
        if form.cancel.data:
            app.logger.info("%s manually cancelling purchase %s", current_user.name, purchase.id)
            payment.lock()

            try:
                purchase.cancel()
            except StateException as e:
                msg = f"Could not cancel purchase {purchase_id}: {e}"
                app.logger.warning(msg)
                flash(msg)
                return redirect(url_for("admin.payment", payment_id=payment.id))

            purchase.payment_id = None
            payment.amount -= purchase.price_tier.get_price(payment.currency).value

            db.session.commit()

            flash(f"Purchase {purchase.id} cancelled")
            return redirect(url_for("admin.payment", payment_id=payment.id))

    return render_template(
        "admin/payments/purchase-cancel.html",
        payment=payment,
        purchase=purchase,
        form=form,
    )
