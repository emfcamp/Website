from datetime import datetime, timedelta
import logging

from flask import (
    render_template, redirect, request, flash,
    url_for, current_app as app
)
from flask_login import login_required, current_user
from flask_mail import Message
from wtforms import SubmitField, HiddenField
from wtforms.validators import Required, AnyOf

from main import db, mail
from ..common import get_user_currency, feature_enabled
from ..common.forms import Form
from ..common.receipt import attach_tickets
from . import get_user_payment_or_abort, lock_user_payment_or_abort
from . import payments

logger = logging.getLogger(__name__)


def transfer_start(payment):
    if not feature_enabled('BANK_TRANSFER'):
        return redirect(url_for('tickets.pay'))

    if get_user_currency() == 'EUR' and not feature_enabled('BANK_TRANSFER_EURO'):
        return redirect(url_for('tickets.pay'))

    logger.info("Created bank payment %s (%s)", payment.id, payment.bankref)

    # No extra preparation required for bank transfer. We can go straight to inprogress.

    if payment.currency == 'GBP':
        days = app.config.get('EXPIRY_DAYS_TRANSFER')
    elif payment.currency == 'EUR':
        days = app.config.get('EXPIRY_DAYS_TRANSFER_EURO')

    payment.expires = datetime.utcnow() + timedelta(days=days)
    payment.state = "inprogress"

    for purchase in payment.purchases:
        purchase.set_state('payment-pending')

    db.session.commit()

    msg = Message("Your EMF ticket purchase",
                  sender=app.config['TICKETS_EMAIL'],
                  recipients=[current_user.email])
    msg.body = render_template("emails/tickets-purchased-email-banktransfer.txt",
                               user=current_user, payment=payment)
    mail.send(msg)

    return redirect(url_for('payments.transfer_waiting', payment_id=payment.id))


class TransferChangeCurrencyForm(Form):
    currency = HiddenField('New currency', [Required(), AnyOf(['EUR', 'GBP'])])
    change = SubmitField('Change currency')

@payments.route("/pay/transfer/<int:payment_id>/waiting")
@login_required
def transfer_waiting(payment_id):
    form = TransferChangeCurrencyForm(request.form)

    payment = get_user_payment_or_abort(
        payment_id, 'banktransfer',
        valid_states=['inprogress'],
    )

    if payment.currency == 'GBP':
        form.currency.data = 'EUR'
    elif payment.currency == 'EUR':
        form.currency.data = 'GBP'

    return render_template('transfer-waiting.html', payment=payment,
                           form=form, days=app.config['EXPIRY_DAYS_TRANSFER'])


@payments.route("/pay/transfer/<int:payment_id>/change-currency", methods=['POST'])
@login_required
def transfer_change_currency(payment_id):
    payment = lock_user_payment_or_abort(
        payment_id, 'banktransfer',
        valid_states=['inprogress'],
    )

    form = TransferChangeCurrencyForm(request.form)
    if form.validate_on_submit():
        if form.change.data:
            logger.info('Changing currency for bank transfer %s', payment.id)

            currency = form.currency.data

            if currency == payment.currency:
                flash("Currency is already {}".format(currency))
                return redirect(url_for('payments.transfer_waiting', payment_id=payment.id))

            payment.change_currency(currency)
            db.session.commit()

            logging.info('Payment %s changed to %s', payment.id, currency)
            flash("Currency changed to {}".format(currency))

        return redirect(url_for('payments.transfer_waiting', payment_id=payment.id))

    return redirect(url_for('payments.transfer_waiting', payment_id=payment.id))


class TransferCancelForm(Form):
    yes = SubmitField('Cancel transfer')


@payments.route("/pay/transfer/<int:payment_id>/cancel", methods=['GET', 'POST'])
@login_required
def transfer_cancel(payment_id):
    payment = lock_user_payment_or_abort(
        payment_id, 'banktransfer',
        valid_states=['new', 'inprogress', 'cancelled'],
    )

    if payment.state == 'cancelled':
        logger.info('Payment %s has already been cancelled', payment.id)
        flash('Payment has already been cancelled')
        return redirect(url_for('users.tickets'))

    form = TransferCancelForm(request.form)
    if form.validate_on_submit():
        if form.yes.data:
            logger.info('Cancelling bank transfer %s', payment.id)
            payment.cancel()
            db.session.commit()

            logging.info('Payment %s cancelled', payment.id)
            flash('Payment cancelled')

        return redirect(url_for('users.tickets'))

    return render_template('transfer-cancel.html', payment=payment, form=form)


def send_confirmation(payment):
    msg = Message("Electromagnetic Field ticket purchase update",
                  sender=app.config['TICKETS_EMAIL'],
                  recipients=[payment.user.email])
    msg.body = render_template("emails/tickets-paid-email-banktransfer.txt",
                  user=payment.user, payment=payment)

    if feature_enabled('ISSUE_TICKETS'):
        attach_tickets(msg, payment.user)

    mail.send(msg)
    db.session.commit()

