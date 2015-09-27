from main import app, db, mail
from models import Payment, StripePayment, TicketType, Ticket
from models.user import User
from views import get_basket

from flask import (
    render_template, redirect, url_for, abort, session, flash
)
from flask.ext.login import login_required, current_user, login_user
from flask_mail import Message

from sqlalchemy.sql.functions import func
from sqlalchemy.exc import IntegrityError

from decimal import Decimal

def get_user_payment_or_abort(payment_id, provider=None, valid_states=None, allow_admin=False):
    try:
        payment = Payment.query.get(payment_id)
    except Exception, e:
        app.logger.warning('Exception %r getting payment %s', e, payment_id)
        abort(404)

    if not (payment.user == current_user or (allow_admin and current_user.admin)):
        app.logger.warning('User not allowed to access payment %s', payment_id)
        abort(404)

    if provider and payment.provider != provider:
        app.logger.warning('Payment %s is of type %s, not %s', payment.provider, provider)
        abort(404)

    if valid_states and payment.state not in valid_states:
        app.logger.warning("Payment %s is %s, not one of %s", payment_id, payment.state, valid_states)
        abort(404)

    return payment


@app.route("/pay/terms")
def ticket_terms():
    return render_template('terms.html')

@app.route("/pay/choose")
def pay_choose():
    basket, total = get_basket()

    if not basket:
        redirect(url_for('tickets'))

    # Implicit user signup
    if current_user.is_anonymous():
        # ToDo: Make user.name optional. See #223
        email = session['anonymous_account_email']
        user = User(email, "NULL")
        user.generate_random_password()
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError, e:
            app.logger.warn('Adding user raised %r, assuming duplicate email', e)
            flash("This email address %s is already in use. Please log in, or reset your password if you've forgotten it." % (email))
            return redirect(url_for('tickets_info'))
        login_user(user)

        # send a welcome email.
        msg = Message("Welcome to Electromagnetic Field",
                sender=app.config['TICKETS_EMAIL'],
                recipients=[user.email])
        msg.body = render_template("emails/tickets-signup-email.txt", user=user)
        mail.send(msg)
        app.logger.info('Created new user with email %s and id %s', email, user.id)
        current_user.id = user.id

    return render_template('payment-choose.html', basket=basket, total=total, StripePayment=StripePayment)


@app.route('/payment/<int:payment_id>/invoice')
@login_required
def payment_invoice(payment_id):
    payment = get_user_payment_or_abort(payment_id, allow_admin=True)

    invoice_lines = payment.tickets.join(TicketType). \
        with_entities(TicketType, func.count(Ticket.type_id)). \
        group_by(TicketType).order_by(TicketType.order).all()

    ticket_sum = sum(tt.get_price_ex_vat(payment.currency) * count for tt, count in invoice_lines)
    if payment.provider == 'stripe':
        premium = payment.__class__.premium(payment.currency, ticket_sum)
    else:
        premium = Decimal(0)

    subtotal = ticket_sum + premium
    vat = subtotal * Decimal('0.2')
    app.logger.debug('Invoice subtotal %s + %s = %s', ticket_sum, premium, subtotal)

    # FIXME: we should use a currency-specific quantization here (or rounder numbers)
    if subtotal + vat - payment.amount > Decimal('0.01'):
        app.logger.error('Invoice total mismatch: %s + %s - %s = %s', subtotal, vat, payment.amount, subtotal + vat - payment.amount)
        flash('Your invoice cannot currently be displayed')
        return redirect(url_for('tickets'))

    app.logger.debug('Invoice total: %s + %s = %s', subtotal, vat, payment.amount)

    due_date = min(t.expires for t in payment.tickets)

    return render_template('invoice.html', payment=payment, invoice_lines=invoice_lines,
                           premium=premium, subtotal=subtotal, vat=vat, due_date=due_date)


import banktransfer  # noqa
import gocardless  # noqa
import stripe  # noqa

