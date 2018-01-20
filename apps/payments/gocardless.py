import logging
from datetime import datetime, timedelta
import re
import hmac
import hashlib
import json

from flask import (
    render_template, redirect, request, flash,
    url_for, current_app as app, abort,
)
from flask_login import login_required
from flask_mail import Message
from wtforms import SubmitField
import gocardless_pro.errors
from sqlalchemy.orm.exc import NoResultFound

from main import db, mail, external_url, gocardless_client, csrf
from models.payment import GoCardlessPayment
from ..common import feature_enabled
from ..common.receipt import attach_tickets
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
    logger.info("Starting GoCardless flow for payment %s", payment.id)

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

    logger.debug('GoCardless redirect ID: %s', redirect_flow.id)
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
        logging.error('Invalid redirect_flow_id for payment %s: %s', payment.id, repr(redirect_id))
        abort(400)

    logger.info("Completing GoCardless payment %s", payment.id)

    try:
        # We've already validated the redirect_id, so we don't expect this to fail
        redirect_flow = gocardless_client.redirect_flows.complete(
            payment.redirect_id,
            params={"session_token": str(payment.id)},
        )
        payment.mandate = redirect_flow.links.mandate

    except gocardless_pro.errors.InvalidStateError as e:
        # Assume the webhook will do its magic
        logging.error('InvalidStateError from GoCardless confirming mandate: %s', e.message)
        flash("An error occurred with your mandate, please check below or contact {}".format(app.config['TICKETS_EMAIL'][1]))
        return redirect(url_for('tickets.main'))

    except Exception as e:
        logger.error("Exception %s confirming mandate", repr(e))
        flash("An error occurred with your payment, please contact {}".format(app.config['TICKETS_EMAIL'][1]))
        return redirect(url_for('tickets.main'))

    try:
        gc_payment = gocardless_client.payments.create(params={
            "amount": payment.amount_int,
            "currency": payment.currency,
            "links": {
                "mandate": payment.mandate,
            },
            "metadata": {
                "payment_id": str(payment.id),
            },
        }, headers={'Idempotency-Key': str(payment.id)})
        payment.gcid = gc_payment.id
        payment.state = 'inprogress'

    except Exception as e:
        logger.error("Exception %s confirming payment", repr(e))
        flash("An error occurred with your payment, please contact {}".format(app.config['TICKETS_EMAIL'][1]))
        return redirect(url_for('tickets.main'))

    for t in payment.purchases:
        # We need to make sure of a 5 working days grace
        # for gocardless payments, so push the ticket expiry forwards
        t.expires = datetime.utcnow() + timedelta(days=app.config['EXPIRY_DAYS_GOCARDLESS'])
        t.set_state('payment-pending')
        logger.info("Reset expiry for ticket %s", t.id)

    db.session.commit()

    logger.info("Payment %s completed OK", payment.id)

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

            try:
                gocardless_client.payments.cancel(payment.gcid)

            except gocardless_pro.errors.InvalidStateError as e:
                logging.error('InvalidStateError from GoCardless confirming mandate: %s', e.message)
                flash("An error occurred with your mandate, please check below or contact {}".format(app.config['TICKETS_EMAIL'][1]))
                return redirect(url_for('tickets.main'))

            logger.info('Cancelling GoCardless payment %s', payment.id)
            payment.cancel()
            db.session.commit()

            logger.info('Payment %s cancelled', payment.id)
            flash('Payment cancelled')

        return redirect(url_for('tickets.main'))

    return render_template('gocardless-cancel.html', payment=payment, form=form)


def is_valid_signature(request):
    secret = bytes(app.config.get('GOCARDLESS_WEBHOOK_SECRET'), 'utf-8')
    computed_signature = hmac.new(
        secret, request.data, hashlib.sha256).hexdigest()
    provided_signature = request.headers.get('Webhook-Signature')
    return hmac.compare_digest(provided_signature, computed_signature)

@csrf.exempt
@payments.route("/gocardless-webhook", methods=['POST'])
def gocardless_webhook():
    # Documentation: https://developer.gocardless.com/api-reference/#appendix-webhooks
    # For testing, see https://developer.gocardless.com/getting-started/developer-tools/scenario-simulators/

    logger.debug("GoCardless webhook received: %s", request.data)
    if not is_valid_signature(request):
        logger.error("Unable to validate GoCardless webhook")
        abort(498)

    origin = request.headers.get('Origin')
    if origin not in ['https://api.gocardless.com', 'https://api-sandbox.gocardless.com']:
        logger.error("Invalid webhook origin: %s", origin)
        abort(500)

    content_type = request.headers.get('Content-Type')
    if content_type != 'application/json':
        logger.error("Invalid webhook content type: %s", content_type)
        abort(500)

    try:
        payload = json.loads(request.data.decode('utf-8'))
        for event in payload['events']:
            resource = event['resource_type']
            action = event['action']
            # The examples suggest details is optional, despite being "recommended"
            origin = event.get('details', {}).get('origin')
            cause = event.get('details', {}).get('cause')
            logger.info("Webhook resource type: %s, action: %s, cause: %s, origin: %s", resource, action, cause, origin)

            try:
                handler = webhook_handlers[(resource, action)]
            except KeyError as e:
                try:
                    handler = webhook_handlers[resource, None]
                except KeyError as e:
                    handler = webhook_handlers[(None, None)]

            handler(resource, action, event)

    except Exception as e:
        logger.error("Unexpected exception during webhook: %r", e)
        abort(500)

    # As far as I can tell, the webhook response content is entirely
    # for my benefit, and they only check the first character of the
    # response code. As we log everything, and I don't want GC to be
    # a store of debug info, always return 204 No Content.
    #
    # We therefore don't need to worry about payloads with a mixture
    # of known and unknown events (the documentation is ambiguous).
    return ('', 204)


@webhook()
def gocardless_default(resource, action, event):
    logger.info("Default handler called for %s", event)


# https://developer.gocardless.com/api-reference/#events-payment-actions
@webhook('payments', 'created')
@webhook('payments', 'submitted')
@webhook('payments', 'paid_out')
def gocardless_payment_do_nothing(resource, action, event):
    gcid = event['links']['payment']
    try:
        payment = GoCardlessPayment.query.filter_by(gcid=gcid).one()
    except NoResultFound:
        logger.warn("Payment for payment %s not found, skipping", gcid)
        return

    logging.info("Received %s action for gcid %s, payment %s",
                 action, gcid, payment.id)


@webhook('payments', 'failed')
@webhook('payments', 'cancelled')
def gocardless_payment_cancelled(resource, action, event):

    gcid = event['links']['payment']
    try:
        payment = GoCardlessPayment.query.filter_by(gcid=gcid).one()
    except NoResultFound:
        logger.warn("Payment for payment %s not found, skipping", gcid)
        return

    logger.info("Received cancelled action for gcid %s, payment %s",
                gcid, payment.id)

    gc_payment = gocardless_client.payments.get(payment.gcid)
    if gc_payment.status != 'cancelled':
        logger.error("Payment status is %s (should be cancelled), ignoring", gc_payment.status)
        return

    if payment.state == 'cancelled':
        logger.info('Payment is already cancelled, skipping')
        return

    if payment.state != 'inprogress':
        logger.error("Current payment state is %s (should be inprogress), ignoring", payment.state)
        return

    logger.info("Setting payment %s to cancelled", payment.id)
    payment.cancel()
    db.session.commit()


@webhook('payments', 'confirmed')
def gocardless_payment_paid(resource, action, event):

    gcid = event['links']['payment']
    try:
        payment = GoCardlessPayment.query.filter_by(gcid=gcid).one()
    except NoResultFound:
        logger.warn("Payment for payment %s not found, skipping", gcid)
        return

    logger.info("Received confirmed action for gcid %s, payment %s",
                gcid, payment.id)

    gc_payment = gocardless_client.payments.get(payment.gcid)
    if gc_payment.status != 'paid':
        logger.error("Payment status is %s (should be paid), ignoring", gc_payment.status)
        return

    if payment.state == 'paid':
        logger.info('Payment is already paid, skipping')
        return

    if payment.state != 'inprogress':
        logger.error("Current payment state is %s (should be inprogress), ignoring", payment.state)
        return

    logger.info("Setting payment %s to paid", payment.id)
    payment.paid()
    db.session.commit()

    msg = Message("Your EMF ticket payment has been confirmed",
                  sender=app.config['TICKETS_EMAIL'],
                  recipients=[payment.user.email])
    msg.body = render_template('emails/tickets-paid-email-gocardless.txt',
                               user=payment.user, payment=payment)

    if feature_enabled('ISSUE_TICKETS'):
        attach_tickets(msg, payment.user)

    mail.send(msg)
    db.session.commit()

