import logging
from datetime import datetime, timedelta

from flask import (
    render_template, redirect, request, flash,
    url_for, current_app as app
)
from flask_login import login_required
from flask_mail import Message
from wtforms import SubmitField

from main import db, mail, external_url, gocardless_client
from ..common import feature_enabled
from ..common.forms import Form
from . import get_user_payment_or_abort
from . import payments

logger = logging.getLogger(__name__)

webhook_handlers = {}

def webhook(resource=None, action=None):
    def inner(f):
        webhook_handlers[(resource, action)] = f
        return f
    return inner

def gocardless_start(payment):
    logger.info("Created GoCardless payment %s", payment.id)

    redirect_flow = gocardless_client.redirect_flows.create(params={
        "description": "Electromagnetic Field",
        "session_token": payment.id,
        "success_redirect_url": external_url('payments.gocardless_mandate', payment_id=payment.id)
    })

    logger.debug('GoCardless Redirect ID: %s', redirect_flow.id)
    logger.debug('GoCardless Redirect URL: %s', redirect_flow.redirect_url)

    payment.redirect_id = redirect_flow.id
    db.session.commit()

    return redirect(redirect_flow.redirect_url)


@payments.route("/pay/gocardless/<int:payment_id>/mandate")
@login_required
def gocardless_mandate(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'gocardless',
        valid_states=['new'],
    )
    logger.info("Completing payment %s, gcid %s", payment.id, request.args.get('resource_id'))

    try:
        params = {"session_token": payment.id}
        redirect_flow = gocardless_client.redirect_flow \
                                         .complete(payment.redirect_id,
                                                   params=params)
        payment.mandate = redirect_flow.links.mandate
    except Exception as e:
        logger.error("Exception %r confirming payment", e)
        flash("An error occurred with your payment, please contact %s" % app.config['TICKETS_EMAIL'][1])
        return redirect(url_for('tickets.main'))

    try:
        gcid = gocardless_client.payments.create(payment.payment_params(),
                                                 headers={ 'Idempotency-Key': 'random_key' })
        payment.gcid = gcid
        payment.status = "inprogress"
    except Exception as e:
        logger.error("Exception %r confirming payment", e)
        flash("An error occurred with your payment, please contact %s" % app.config['TICKETS_EMAIL'][1])
        return redirect(url_for('tickets.main'))

    for t in payment.purchases:
        # We need to make sure of a 5 working days grace
        # for gocardless payments, so push the ticket expiry forwards
        t.expires = datetime.utcnow() + timedelta(days=app.config['EXPIRY_DAYS_GOCARDLESS'])
        logger.info("Reset expiry for ticket %s", t.id)

    db.session.commit()

    logger.info("Payment %s completed OK", payment.id)

    # should we send the resource_uri in the bill email?
    msg = Message("Your EMF ticket purchase",
                  sender=app.config['TICKETS_EMAIL'],
                  recipients=[payment.user.email])
    msg.body = render_template("emails/tickets-purchased-email-gocardless.txt",
                               user=payment.user, payment=payment)
    mail.send(msg)

    return redirect(url_for('.gocardless_waiting', payment_id=payment.id))

@payments.route('/pay/gocardless/<int:payment_id>/waiting')
@login_required
def gocardless_waiting(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'gocardless',
        valid_states=['new', 'inprogress', 'paid'],
    )
    return render_template('gocardless-waiting.html', payment=payment,
                           days=app.config['EXPIRY_DAYS_GOCARDLESS'])

@payments.route('/pay/gocardless/<int:payment_id>/tryagain')
@login_required
def gocardless_tryagain(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'gocardless',
        valid_states=['new'],
    )

    if not feature_enabled('GOCARDLESS'):
        logger.error('Unable to retry payment %s as GoCardless is disabled', payment.id)
        flash('GoCardless is currently unavailable. Please try again later')
        return redirect(url_for('tickets.main'))

    logger.info("Trying payment %s again", payment.id)
    gocardless_client.payments.retry(payment.gcid)
    flash('Your gocardless payment has been retried')
    return redirect('tickets')

class GoCardlessCancelForm(Form):
    yes = SubmitField('Cancel payment')

@payments.route("/pay/gocardless/<int:payment_id>/cancel", methods=['GET', 'POST'])
@login_required
def gocardless_cancel(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'gocardless',
        valid_states=['new', 'cancelled'],  # once it's inprogress, there's potentially money moving around
    )

    if payment.state == 'cancelled':
        logger.info('Payment %s has already been cancelled', payment.id)
        flash('Payment has already been cancelled')
        return redirect(url_for('tickets.main'))

    form = GoCardlessCancelForm(request.form)
    if form.validate_on_submit():
        if form.yes.data:
            logger.info('Cancelling GoCardless payment %s', payment.id)
            payment.cancel()
            db.session.commit()

            logger.info('Payment %s cancelled', payment.id)
            flash('Payment cancelled')

        return redirect(url_for('tickets.main'))

    return render_template('gocardless-cancel.html', payment=payment, form=form)


# TODO resurrect these endpoints...

# @webhook('bill')
# @webhook('bill', 'created')
# @webhook('bill', 'withdrawn')
# @webhook('bill', 'failed')
# def gocardless_bill(resource, action, data):

# @webhook('bill', 'cancelled')
# def gocardless_bill_cancelled(resource, action, data):


# @webhook('bill', 'paid')
# def gocardless_bill_paid(resource, action, data):
