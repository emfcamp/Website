from main import app, db, gocardless, mail, csrf
from models.payment import GoCardlessPayment
from views import feature_flag, Form
from views.payment import get_user_payment_or_abort
from views.tickets import add_payment_and_tickets

from flask import (
    render_template, redirect, request, flash,
    url_for, abort,
)
from flask.ext.login import login_required
from flask_mail import Message

from wtforms import SubmitField

from sqlalchemy.orm.exc import NoResultFound

import simplejson
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

webhook_handlers = {}
def webhook(resource=None, action=None):
    def inner(f):
        webhook_handlers[(resource, action)] = f
        return f
    return inner

@app.route("/pay/gocardless-start", methods=['POST'])
@feature_flag('GOCARDLESS')
@login_required
def gocardless_start():
    payment = add_payment_and_tickets(GoCardlessPayment)
    if not payment:
        logging.warn('Unable to add payment and tickets to database')
        flash('Your session information has been lost. Please try ordering again.')
        return redirect(url_for('tickets'))

    logger.info("Created GoCardless payment %s", payment.id)
    db.session.commit()

    bill_url = payment.bill_url("Electromagnetic Field Tickets")
    logger.debug('Bill URL for GoCardless: %s', bill_url)
    return redirect(bill_url)

@app.route('/pay/gocardless/<int:payment_id>/waiting')
@login_required
def gocardless_waiting(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'gocardless',
        valid_states=['new', 'inprogress', 'paid'],
    )
    return render_template('gocardless-waiting.html', payment=payment, days=app.config['EXPIRY_DAYS_GOCARDLESS'])

@app.route('/pay/gocardless/<int:payment_id>/tryagain')
@login_required
def gocardless_tryagain(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'gocardless',
        valid_states=['new'],
    )

    if not app.config.get('GOCARDLESS'):
        logger.error('Unable to retry payment %s as GoCardless is disabled', payment.id)
        flash('GoCardless is currently unavailable. Please try again later')
        return redirect(url_for('tickets'))

    logger.info("Trying payment %s again", payment.id)
    bill_url = payment.bill_url("Electromagnetic Field Tickets")
    logger.debug('Bill URL for GoCardless: %s', bill_url)
    return redirect(bill_url)

@app.route("/pay/gocardless/<int:payment_id>/complete")
@login_required
def gocardless_complete(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'gocardless',
        valid_states=['new'],
    )
    logger.info("Completing payment %s, gcid %s", payment.id, request.args.get('resource_id'))

    try:
        gocardless.client.confirm_resource(request.args)

        if request.args["resource_type"] != "bill":
            raise ValueError("GoCardless resource type %s, not bill" % request.args['resource_type'])

        gcid = request.args["resource_id"]

    except Exception, e:
        logger.error("Exception %r confirming payment", e)
        flash("An error occurred with your payment, please contact %s" % app.config['TICKETS_EMAIL'][1])
        return redirect(url_for('tickets'))

    # keep the gocardless reference so we can find the payment when we get called by the webhook
    payment.gcid = gcid
    payment.state = 'inprogress'

    for t in payment.tickets:
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
    msg.body = render_template("tickets-purchased-email-gocardless.txt",
        user=payment.user, payment=payment)
    mail.send(msg)

    return redirect(url_for('gocardless_waiting', payment_id=payment.id))


class GoCardlessCancelForm(Form):
    yes = SubmitField('Cancel payment')

@app.route("/pay/gocardless/<int:payment_id>/cancel", methods=['GET', 'POST'])
@login_required
def gocardless_cancel(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'gocardless',
        valid_states=['new', 'cancelled'], # once it's inprogress, there's potentially money moving around
    )

    if payment.state == 'cancelled':
        logger.info('Payment %s has already been cancelled', payment.id)
        flash('Payment has already been cancelled')
        return redirect(url_for('tickets'))

    form = GoCardlessCancelForm(request.form)
    if form.validate_on_submit():
        if form.yes.data:
            logger.info('Cancelling GoCardless payment %s', payment.id)
            payment.cancel()
            db.session.commit()

            logger.info('Payment %s cancelled', payment.id)
            flash('Payment cancelled')

        return redirect(url_for('tickets'))

    return render_template('gocardless-cancel.html', payment=payment, form=form)


@csrf.exempt
@app.route("/gocardless-webhook", methods=['POST'])
def gocardless_webhook():
    # Documentation: https://developer.gocardless.com/#webhook-overview

    logger.debug(request.data)
    json_data = simplejson.loads(request.data)

    try:
        data = json_data['payload']

        if not gocardless.client.validate_webhook(data):
            logger.error("Unable to validate GoCardless webhook")
            abort(403)

        resource = data['resource_type']
        action = data['action']
        logger.info("Webhook resource type %s action %s", resource, action)

        try:
            handler = webhook_handlers[(resource, action)]
        except KeyError, e:
            try:
                handler = webhook_handlers[resource, None]
            except KeyError, e:
                handler = webhook_handlers[(None, None)]

        return handler(resource, action, data)

    except Exception, e:
        logger.error('Unexcepted exception during webhook: %r', e)
        abort(500)

@webhook('bill')
@webhook('bill', 'created')
@webhook('bill', 'withdrawn')
@webhook('bill', 'failed')
def gocardless_bill(resource, action, data):
    # Bills are all available on the website
    logger.warn('Default handler called for %s', data)
    try:
        for bill in data['bills']:
            try:
                gcid = bill['id']
                payment = GoCardlessPayment.query.filter_by(gcid=gcid).one()
            except NoResultFound:
                logger.warn("Payment for bill %s not found, skipping", gcid)
                continue

            logging.info('Received %s action for gcid %s, payment %s',
                         action, gcid, payment.id)

    except Exception, e:
        logger.error('Unexcepted exception during webhook: %r', e)
        abort(501)

    return ('', 200)

@webhook('bill', 'cancelled')
def gocardless_bill_cancelled(resource, action, data):

    for bill in data['bills']:
        gcid = bill['id']
        try:
            payment = GoCardlessPayment.query.filter_by(gcid=gcid).one()
        except NoResultFound:
            logger.warn("Payment for bill %s not found, skipping", gcid)
            continue

        logger.info("Received cancelled action for gcid %s, payment %s",
                    gcid, payment.id)

        if bill['status'] != 'cancelled':
            logger.warn("Bill status is %s (should be cancelled), failing", bill['status'])
            abort(409)

        if payment.state == 'cancelled':
            logger.info('Payment is already cancelled, skipping')
            continue

        if payment.state != 'inprogress':
            logger.warning("Current payment state is %s (should be inprogress), failing", payment.state)
            abort(409)

        logger.info("Setting payment %s to cancelled", payment.id)
        payment.cancel()
        db.session.commit()

    return ('', 200)

@webhook('bill', 'paid')
def gocardless_bill_paid(resource, action, data):

    for bill in data['bills']:
        gcid = bill['id']
        try:
            payment = GoCardlessPayment.query.filter_by(gcid=gcid).one()
        except NoResultFound:
            logger.warn("Payment for bill %s not found, skipping", gcid)
            continue

        logger.info("Received paid action for gcid %s, payment %s",
                    gcid, payment.id)

        if bill['status'] != 'paid':
            logger.warn("Bill status is %s (should be paid), failing", bill['status'])
            abort(409)

        if payment.state == 'paid':
            logger.info('Payment is already paid, skipping')
            continue

        if payment.state != 'inprogress':
            logger.warning("Current payment state is %s (should be inprogress), failing", payment.state)
            abort(409)

        logger.info("Setting payment %s to paid", payment.id)
        payment.paid()
        db.session.commit()

        msg = Message("Your EMF ticket payment has been confirmed",
            sender=app.config['TICKETS_EMAIL'],
            recipients=[payment.user.email])
        msg.body = render_template("tickets-paid-email-gocardless.txt",
            user=payment.user, payment=payment)
        mail.send(msg)

    return ('', 200)


