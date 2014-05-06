from main import app, db, mail
from models.payment import BankPayment
from views import feature_flag
from views.payment import get_user_payment_or_abort
from views.tickets import add_payment_and_tickets

from flask import (
    render_template, redirect, request, flash,
    url_for,
)
from flask.ext.login import login_required, current_user
from flaskext.mail import Message

from flask_wtf import Form
from wtforms import SubmitField

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

@app.route("/pay/transfer-start", methods=['POST'])
@feature_flag('BANK_TRANSFER')
@login_required
def transfer_start():
    payment = add_payment_and_tickets(BankPayment)
    if not payment:
        logging.warn('Unable to add payment and tickets to database')
        flash('Your session information has been lost. Please try ordering again.')
        return redirect(url_for('tickets'))

    logger.info("Created bank payment %s (%s)", payment.id, payment.bankref)

    payment.state = "inprogress"
    db.session.commit()

    msg = Message("Your EMF ticket purchase",
        sender=app.config['TICKETS_EMAIL'],
        recipients=[current_user.email]
    )
    msg.body = render_template("tickets-purchased-email-banktransfer.txt",
        user=current_user, payment=payment)
    mail.send(msg)

    return redirect(url_for('transfer_waiting', payment_id=payment.id))

@app.route("/pay/transfer/<int:payment_id>/waiting")
@login_required
def transfer_waiting(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'banktransfer',
        valid_states=['inprogress'],
    )
    return render_template('transfer-waiting.html', payment=payment, days=app.config['EXPIRY_DAYS'])


class TransferCancelForm(Form):
    yes = SubmitField('Cancel transfer')

@app.route("/pay/transfer/<int:payment_id>/cancel", methods=['GET', 'POST'])
@login_required
def transfer_cancel(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'banktransfer',
        valid_states=['new', 'inprogress'],
    )

    form = TransferCancelForm(request.form)
    if form.validate_on_submit():
        if form.yes.data:
            logger.info('Cancelling bank transfer %s', payment.id)
            for t in payment.tickets.all():
                t.expiry = datetime.now()
            payment.state = 'cancelled'
            db.session.commit()

            logging.info('Payment %s cancelled', payment.id)
            flash('Payment cancelled')

        return redirect(url_for('tickets'))

    return render_template('transfer-cancel.html', payment=payment, form=form)

