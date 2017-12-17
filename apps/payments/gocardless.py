import logging
from datetime import datetime, timedelta
import re

from flask import (
    render_template, redirect, request, flash,
    url_for, current_app as app, abort,
)
from flask_login import login_required
from flask_mail import Message
from wtforms import SubmitField
import gocardless_pro.errors

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
    logger.info("Starting GoCardless flow for payment {}", payment.id)

    prefilled_customer = {
        "email": payment.user.email,
    }
    match = re.match(r'^ *([^ ,]+) +([^ ,]+) *$', payment.user.name)
    if match:
        prefilled_customer.update({
            'given_name': match.group(1),
            'family_name': match.group(2),
        })

    redirect_flow = gocardless_client.redirect_flows.create(params={
        "description": "Electromagnetic Field",
        "session_token": str(payment.id),
        "success_redirect_url": external_url('payments.gocardless_complete', payment_id=payment.id),
        "prefilled_customer": prefilled_customer,
    })

    logger.debug('GoCardless redirect ID: {}', redirect_flow.id)
    assert payment.redirect_id is None
    payment.redirect_id = redirect_flow.id
    db.session.commit()

    return redirect(redirect_flow.redirect_url)


@payments.route("/pay/gocardless/<int:payment_id>/complete")
@login_required
def gocardless_complete(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'gocardless',
        valid_states=['new'],
    )
    redirect_id = request.args.get('redirect_flow_id')
    if redirect_id != payment.redirect_id:
        logging.error('Invalid redirect_flow_id for payment {}: {}', payment.id, repr(redirect_id))
        abort(400)

    logger.info("Completing GoCardless payment {}", payment.id)

    try:
        # We've already validated the redirect_id, so we don't expect this to fail
        redirect_flow = gocardless_client.redirect_flows.complete(
            payment.redirect_id,
            params={"session_token": str(payment.id)},
        )
        payment.mandate = redirect_flow.links.mandate

    except gocardless_pro.errors.InvalidStateError as e:
        # Assume the webhook will do its magic
        logging.error('InvalidStateError from GoCardless confirming mandate: {}', e.message)
        flash("An error occurred with your mandate, please check below or contact {}".format(app.config['TICKETS_EMAIL'][1]))
        return redirect(url_for('tickets.main'))

    except Exception as e:
        logger.error("Exception {} confirming mandate", repr(e))
        flash("An error occurred with your payment, please contact {}".format(app.config['TICKETS_EMAIL'][1]))
        return redirect(url_for('tickets.main'))

    try:
        gcpayment = gocardless_client.payments.create(params={
            "amount": payment.amount_int,
            "currency": payment.currency,
            "links": {
                "mandate": payment.mandate,
            },
            "metadata": {
                "payment_id": str(payment.id),
            },
        }, headers={'Idempotency-Key': str(payment.id)})
        payment.gcid = gcpayment.id
        payment.status = "inprogress"

    except Exception as e:
        logger.error("Exception {} confirming payment", repr(e))
        flash("An error occurred with your payment, please contact {}".format(app.config['TICKETS_EMAIL'][1]))
        return redirect(url_for('tickets.main'))

    for t in payment.purchases:
        # We need to make sure of a 5 working days grace
        # for gocardless payments, so push the ticket expiry forwards
        t.expires = datetime.utcnow() + timedelta(days=app.config['EXPIRY_DAYS_GOCARDLESS'])
        t.set_state('payment-pending')
        logger.info("Reset expiry for ticket {}", t.id)

    db.session.commit()

    logger.info("Payment {} completed OK", payment.id)

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

    logger.info("Trying payment {} again", payment.id)
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
