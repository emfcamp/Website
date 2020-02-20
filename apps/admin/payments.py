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
from flask_login import current_user
from flask_mail import Message

from wtforms.validators import InputRequired
from wtforms import SubmitField, BooleanField, FieldList, FormField

from sqlalchemy.sql.functions import func
import gocardless_pro.errors

from main import db, mail, stripe, gocardless_client
from models.payment import (
    Payment,
    BankPayment,
    BankRefund,
    StripeRefund,
    StateException,
)
from models.purchase import Purchase
from ..common.forms import Form, HiddenIntegerField
from ..payments.stripe import (
    StripeUpdateUnexpected,
    StripeUpdateConflict,
    stripe_update_payment,
    stripe_payment_refunded,
)
from ..payments.gocardless import gocardless_update_payment


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

            if payment.reminder_sent:
                app.logger.error("Reminder for payment %s already sent", payment.id)
                flash(
                    "Cannot send duplicate reminder email for payment %s" % payment.id
                )
                return redirect(url_for("admin.expiring"))

            msg = Message(
                "Electromagnetic Field ticket purchase update",
                sender=app.config["TICKETS_EMAIL"],
                recipients=[payment.user.email],
            )
            msg.body = render_template("emails/tickets-reminder.txt", payment=payment)
            mail.send(msg)

            payment.reminder_sent = True
            db.session.commit()

            flash("Reminder email for payment %s sent" % payment.id)
            return redirect(url_for("admin.expiring"))

    return render_template(
        "admin/payments/payment-send-reminder.html", payment=payment, form=form
    )


class UpdatePaymentForm(Form):
    update = SubmitField("Update payment")


@admin.route("/payment/<int:payment_id>/update", methods=["GET", "POST"])
def update_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    if payment.provider not in {"gocardless", "stripe"}:
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

            if payment.provider == "gocardless":
                gocardless_update_payment(payment)

            elif payment.provider == "stripe":
                try:
                    stripe_update_payment(payment)
                except StripeUpdateConflict:
                    flash("Unable to update due to a status conflict")
                    return redirect(
                        url_for("admin.update_payment", payment_id=payment.id)
                    )
                except StripeUpdateUnexpected:
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
        if form.cancel.data and (payment.provider in ["banktransfer", "gocardless"]):
            app.logger.info(
                "%s manually cancelling payment %s", current_user.name, payment.id
            )

            payment.lock()

            if payment.provider == "gocardless" and payment.gcid is not None:
                try:
                    gocardless_client.payments.cancel(payment.gcid)

                except gocardless_pro.errors.InvalidStateError as e:
                    app.logger.error(
                        "InvalidStateError from GoCardless cancelling payment: %s",
                        e.message,
                    )
                    flash("Error cancelling with GoCardless")

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
    payments = (
        Payment.query.filter_by(state="refund-requested")
        .join(Purchase)
        .with_entities(Payment, func.count(Purchase.id).label("purchase_count"))
        .group_by(Payment)
        .order_by(Payment.id)
        .all()
    )

    return render_template("admin/payments/requested_refunds.html", payments=payments)


class ManualRefundForm(Form):
    refund = SubmitField("Refund payment")


@admin.route("/payment/<int:payment_id>/manual-refund", methods=["GET", "POST"])
def manual_refund(payment_id):
    """ Mark an entire payment as refunded for book-keeping purposes.
        Doesn't actually take any steps to return money to the user. """

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
    payment = Payment.query.get_or_404(payment_id)

    valid_states = ["charged", "paid", "partrefunded", "refund-requested"]
    if payment.state not in valid_states:
        app.logger.warning(
            "Payment %s is %s, not one of %s", payment_id, payment.state, valid_states
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
            f._disabled = False
        else:
            f._disabled = True

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
                    app.logger.warn("Exception %r refunding payment", e)
                    flash(
                        "An error occurred refunding with Stripe. Please check the state of the payment."
                    )
                    return redirect(url_for(".refund", payment_id=payment.id))

                refund.refundid = stripe_refund.id
                if stripe_refund.status != "succeeded":
                    # Should never happen according to the docs
                    app.logger.warn(
                        "Refund status is %s, not succeeded", stripe_refund.status
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
