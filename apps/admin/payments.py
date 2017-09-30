# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from datetime import datetime, timedelta

from . import admin, admin_required

from flask import (
    render_template, redirect, request, flash,
    url_for, abort, current_app as app
)
from flask.ext.login import current_user
from flask_mail import Message

from wtforms.validators import Required
from wtforms import SubmitField, BooleanField, FieldList, FormField

from sqlalchemy.sql.functions import func

from main import db, mail, stripe
from models.payment import Payment, BankPayment, BankRefund, StripeRefund, StateException
from models.purchase import Purchase
# from models.ticket import Ticket
from ..common.forms import Form, HiddenIntegerField
from ..payments.stripe import (
    StripeUpdateUnexpected, StripeUpdateConflict, stripe_update_payment,
    stripe_payment_refunded,
)


@admin.route('/payments')
@admin_required
def payments():
    payments = Payment.query.join(Purchase).with_entities(
        Payment,
        func.min(Purchase.expires).label('first_expires'),
        func.count(Purchase.id).label('ticket_count'),
    ).group_by(Payment).order_by(Payment.id).all()

    return render_template('admin/payments.html', payments=payments)


@admin.route('/payments/expiring')
@admin_required
def expiring():
    expiring = BankPayment.query.join(Purchase).filter(
        BankPayment.state == 'inprogress',
        Purchase.expires < datetime.utcnow() + timedelta(days=3),
    ).with_entities(
        BankPayment,
        func.min(Purchase.expires).label('first_expires'),
        func.count(Purchase.id).label('ticket_count'),
    ).group_by(BankPayment).order_by('first_expires').all()

    return render_template('admin/payments-expiring.html', expiring=expiring)


class ResetExpiryForm(Form):
    reset = SubmitField("Reset")


@admin.route('/payment/<int:payment_id>/reset-expiry', methods=['GET', 'POST'])
@admin_required
def reset_expiry(payment_id):
    payment = BankPayment.query.get_or_404(payment_id)

    form = ResetExpiryForm()
    if form.validate_on_submit():
        if form.reset.data:
            app.logger.info("%s manually extending expiry for payment %s", current_user.name, payment.id)
            for t in payment.purchases:
                if payment.currency == 'GBP':
                    t.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS_TRANSFER'))
                elif payment.currency == 'EUR':
                    t.expires = datetime.utcnow() + timedelta(
                        days=app.config.get('EXPIRY_DAYS_TRANSFER_EURO'))
                app.logger.info("Reset expiry for ticket %s", t.id)

            db.session.commit()

            flash("Expiry reset for payment %s" % payment.id)
            return redirect(url_for('admin.expiring'))

    return render_template('admin/payment-reset-expiry.html', payment=payment, form=form)


class SendReminderForm(Form):
    remind = SubmitField("Send reminder")


@admin.route('/payment/<int:payment_id>/reminder', methods=['GET', 'POST'])
@admin_required
def send_reminder(payment_id):
    payment = BankPayment.query.get_or_404(payment_id)

    form = SendReminderForm()
    if form.validate_on_submit():
        if form.remind.data:
            app.logger.info("%s sending reminder email to %s <%s> for payment %s",
                            current_user.name, payment.user.name, payment.user.email, payment.id)

            if payment.reminder_sent:
                app.logger.error('Reminder for payment %s already sent', payment.id)
                flash("Cannot send duplicate reminder email for payment %s" % payment.id)
                return redirect(url_for('admin.expiring'))

            msg = Message("Electromagnetic Field ticket purchase update",
                          sender=app.config['TICKETS_EMAIL'],
                          recipients=[payment.user.email])
            msg.body = render_template("emails/tickets-reminder.txt", payment=payment)
            mail.send(msg)

            payment.reminder_sent = True
            db.session.commit()

            flash("Reminder email for payment %s sent" % payment.id)
            return redirect(url_for('admin.expiring'))

    return render_template('admin/payment-send-reminder.html', payment=payment, form=form)


class UpdatePaymentForm(Form):
    update = SubmitField("Update payment")


@admin.route('/payment/<int:payment_id>/update', methods=['GET', 'POST'])
@admin_required
def update_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    if payment.provider != 'stripe':
        abort(404)

    form = UpdatePaymentForm()
    if form.validate_on_submit():
        if form.update.data:
            app.logger.info('Requesting updated status for %s payment %s', payment.provider, payment.id)

            try:
                stripe_update_payment(payment)
            except StripeUpdateConflict:
                flash('Unable to update due to a status conflict')
                return redirect(url_for('admin.update_payment', payment_id=payment.id))
            except StripeUpdateUnexpected:
                flash('Unable to update due to an unexpected response from Stripe')
                return redirect(url_for('admin.update_payment', payment_id=payment.id))

            flash('Payment status updated')
            return redirect(url_for('admin.update_payment', payment_id=payment.id))

    return render_template('admin/payment-update.html', payment=payment, form=form)


class CancelPaymentForm(Form):
    cancel = SubmitField("Cancel payment")


@admin.route('/payment/<int:payment_id>/cancel', methods=['GET', 'POST'])
@admin_required
def cancel_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    if payment.provider == u'stripe':
        msg = 'Cannot cancel stripe payment (id: %s).' % payment_id
        app.logger.warn(msg)
        flash(msg)
        return redirect(url_for('admin.payments'))

    form = CancelPaymentForm()
    if form.validate_on_submit():
        if form.cancel.data and (payment.provider in ['banktransfer', 'gocardless']):
            app.logger.info("%s manually cancelling payment %s", current_user.name, payment.id)
            try:
                payment.cancel()
            except StateException as e:
                msg = 'Could not cancel payment %s: %s' % (payment_id, e)
                app.logger.warn(msg)
                flash(msg)
                return redirect(url_for('admin.payments'))

            db.session.commit()

            flash("Payment %s cancelled" % payment.id)
            return redirect(url_for('admin.expiring'))

    return render_template('admin/payment-cancel.html', payment=payment, form=form)


class RefundPaymentForm(Form):
    refund = SubmitField("Refund payment")


@admin.route('/payment/<int:payment_id>/full-refund', methods=['GET', 'POST'])
@admin_required
def refund_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    form = RefundPaymentForm()
    if form.validate_on_submit():
        if form.refund.data:
            app.logger.info("Manually refunding payment %s", payment.id)
            try:
                payment.manual_refund()

            except StateException as e:
                app.logger.warn('Could not refund payment %s: %s', payment_id, e)
                flash('Could not refund payment due to a state error')
                return redirect(url_for('admin.payments'))

            db.session.commit()

            flash("Payment refunded")
            return redirect(url_for('admin.payments'))

    return render_template('admin/payment-refund.html', payment=payment, form=form)


class PartialRefundTicketForm(Form):
    ticket_id = HiddenIntegerField('Ticket ID', [Required()])
    refund = BooleanField('Refund ticket', default=True)


class PartialRefundForm(Form):
    tickets = FieldList(FormField(PartialRefundTicketForm))
    refund = SubmitField('I have refunded these tickets by bank transfer')
    stripe_refund = SubmitField('Refund through Stripe')


@admin.route("/payment/<int:payment_id>/refund", methods=['GET', 'POST'])
@admin_required
def partial_refund(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    valid_states = ['charged', 'paid', 'partrefunded']
    if payment.state not in valid_states:
        app.logger.warning("Payment %s is %s, not one of %s", payment_id, payment.state, valid_states)
        flash('Payment is not currently refundable')
        return redirect(url_for('.payments'))

    form = PartialRefundForm(request.form)

    if payment.provider != 'stripe':
        form.stripe_refund.data = ''

    if request.method != 'POST':
        for ticket in payment.purchases:
            form.tickets.append_entry()
            form.tickets[-1].ticket_id.data = ticket.id

    tickets_dict = {t.id: t for t in payment.purchases}

    for f in form.tickets:
        f._ticket = tickets_dict[f.ticket_id.data]
        f.refund.label.text = '%s - %s' % (f._ticket.id, f._ticket.type.name)
        if f._ticket.refund_id is None and f._ticket.paid:
            f._disabled = False
        else:
            f._disabled = True

    if form.validate_on_submit():
        if form.refund.data or form.stripe_refund.data:
            tickets = [f._ticket for f in form.tickets if f.refund.data and not f._disabled]
            total = sum(t.price_tier.get_price(payment.currency) for t in tickets)

            if not total:
                flash('Please select some non-free tickets to refund')
                return redirect(url_for('.partial_refund', payment_id=payment.id))

            if any(t.user != payment.user for t in tickets):
                flash('Cannot refund transferred ticket')
                return redirect(url_for('.partial_refund', payment_id=payment.id))

            premium = payment.__class__.premium_refund(payment.currency, total)
            app.logger.info('Refunding %s tickets from payment %s, totalling %s %s and %s %s premium',
                            len(tickets), payment.id, total, payment.currency, premium, payment.currency)

            if form.stripe_refund.data:
                app.logger.info('Refunding using Stripe')
                charge = stripe.Charge.retrieve(payment.chargeid)

                if charge.refunded:
                    # This happened unexpectedly - send the email as usual
                    stripe_payment_refunded(payment)
                    flash('This charge has already been fully refunded.')
                    return redirect(url_for('.partial_refund', payment_id=payment.id))

                payment.state = 'refunding'
                refund = StripeRefund(payment, total + premium)

            else:
                app.logger.info('Refunding out of band')

                payment.state = 'refunding'
                refund = BankRefund(payment, total + premium)

            now = datetime.utcnow()
            for ticket in tickets:
                ticket.paid = False
                if ticket.expires is None or ticket.expires > now:
                    ticket.expires = now
                ticket.refund = refund

            priced_tickets = [t for t in payment.purchases if t.price_tier.get_price(payment.currency)]
            unpriced_tickets = [t for t in payment.purchases if not t.price_tier.get_price(payment.currency)]

            all_refunded = False
            if all(t.refund for t in priced_tickets):
                all_refunded = True
                # Remove remaining free tickets from the payment so they're still valid.
                for ticket in unpriced_tickets:
                    if not ticket.refund:
                        app.logger.info('Removing free ticket %s from refunded payment', ticket.id)
                        if not ticket.paid:
                            # The only thing keeping this ticket from being valid was the payment
                            app.logger.info('Setting orphaned free ticket %s to paid', ticket.id)
                            ticket.paid = True

                        ticket.payment = None
                        ticket.payment_id = None

            db.session.commit()

            if form.stripe_refund.data:
                try:
                    stripe_refund = stripe.Refund.create(
                        charge=payment.chargeid,
                        amount=refund.amount_int)

                except Exception as e:
                    app.logger.warn("Exception %r refunding payment", e)
                    flash('An error occurred refunding with Stripe. Please check the state of the payment.')
                    return redirect(url_for('.partial_refund', payment_id=payment.id))

                refund.refundid = stripe_refund.id
                if stripe_refund.status != 'succeeded':
                    # Should never happen according to the docs
                    app.logger.warn("Refund status is %s, not succeeded", stripe_refund.status)
                    flash('The refund with Stripe was not successful. Please check the state of the payment.')
                    return redirect(url_for('.partial_refund', payment_id=payment.id))

            if all_refunded:
                payment.state = 'refunded'
            else:
                payment.state = 'partrefunded'

            db.session.commit()

            app.logger.info('Payment %s refund complete for a total of %s', payment.id, total + premium)
            flash('Refund for %s %s complete' % (total + premium, payment.currency))

        return redirect(url_for('.payments'))

    refunded_tickets = [t for t in payment.purchases if t.refund]
    return render_template('admin/partial-refund.html', payment=payment, form=form,
                           refunded_tickets=refunded_tickets)
