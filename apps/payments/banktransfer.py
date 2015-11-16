import logging
from flask import (
    render_template, redirect, request, flash,
    url_for, current_app as app
)
from flask.ext.login import login_required, current_user
from flask_mail import Message
from wtforms import SubmitField

from main import db, mail
from models.payment import BankPayment
from ..common import feature_flag, get_user_currency
from ..common.forms import Form
from ..tickets import add_payment_and_tickets
from . import get_user_payment_or_abort, payments

logger = logging.getLogger(__name__)


@payments.route("/pay/transfer-start", methods=['POST'])
@feature_flag('BANK_TRANSFER')
def transfer_start():
    if get_user_currency() == 'EUR' and not app.config.get('BANK_TRANSFER_EURO'):
        return redirect(url_for('.choose'))

    payment = add_payment_and_tickets(BankPayment)
    if not payment:
        logging.warn('Unable to add payment and tickets to database')
        flash('Your session information has been lost. Please try ordering again.')
        return redirect(url_for('tickets.main'))

    logger.info("Created bank payment %s (%s)", payment.id, payment.bankref)

    payment.state = "inprogress"
    db.session.commit()

    msg = Message("Your EMF ticket purchase",
                  sender=app.config['TICKETS_EMAIL'],
                  recipients=[current_user.email])
    msg.body = render_template("emails/tickets-purchased-email-banktransfer.txt",
                               user=current_user, payment=payment)
    mail.send(msg)

    return redirect(url_for('.transfer_waiting', payment_id=payment.id))


@payments.route("/pay/transfer/<int:payment_id>/waiting")
@login_required
def transfer_waiting(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'banktransfer',
        valid_states=['inprogress'],
    )
    return render_template('transfer-waiting.html', payment=payment, days=app.config['EXPIRY_DAYS_TRANSFER'])


class TransferCancelForm(Form):
    yes = SubmitField('Cancel transfer')


@payments.route("/pay/transfer/<int:payment_id>/cancel", methods=['GET', 'POST'])
@login_required
def transfer_cancel(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'banktransfer',
        valid_states=['new', 'inprogress', 'cancelled'],
    )

    if payment.state == 'cancelled':
        logger.info('Payment %s has already been cancelled', payment.id)
        flash('Payment has already been cancelled')
        return redirect(url_for('tickets.main'))

    form = TransferCancelForm(request.form)
    if form.validate_on_submit():
        if form.yes.data:
            logger.info('Cancelling bank transfer %s', payment.id)
            payment.cancel()
            db.session.commit()

            logging.info('Payment %s cancelled', payment.id)
            flash('Payment cancelled')

        return redirect(url_for('tickets.main'))

    return render_template('transfer-cancel.html', payment=payment, form=form)
