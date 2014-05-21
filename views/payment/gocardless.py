from main import app, db, gocardless, mail, csrf
from models.payment import GoCardlessPayment
from views import feature_flag, set_user_currency, Form
from views.payment import get_user_payment_or_abort
from views.tickets import add_payment_and_tickets

from flask import (
    render_template, redirect, request, flash,
    url_for,
)
from flask.ext.login import login_required
from flaskext.mail import Message

from wtforms import SubmitField

from sqlalchemy.orm.exc import NoResultFound

import simplejson
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


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
        valid_states=['new', 'inprogress'],
    )

    if not app.config.get('GOCARDLESS'):
        logger.error('Unable to retry payment %s as GoCardless is disabled', payment.id)
        flash('GoCardless is currently unavailable. Please try again later')
        return redirect(url_for('tickets'))

    logger.info("Trying payment %s again", payment.id)
    bill_url = payment.bill_url("Electromagnetic Field Ticket Deposit")
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
    payment.state = "inprogress"

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
        recipients=[payment.user.email]
    )
    msg.body = render_template("tickets-purchased-email-gocardless.txt",
        user = payment.user, payment=payment)
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
            for t in payment.tickets.all():
                t.expires = datetime.utcnow()
            payment.state = 'cancelled'
            db.session.commit()

            logger.info('Payment %s cancelled', payment.id)
            flash('Payment cancelled')

        return redirect(url_for('tickets'))

    return render_template('gocardless-cancel.html', payment=payment, form=form)


@csrf.exempt
@app.route("/gocardless-webhook", methods=['POST'])
def gocardless_webhook():
    """
        handle the gocardless webhook / callback callback:
        https://gocardless.com/docs/web_hooks_guide#response
        
        we mostly want 'bill'
        
        GoCardless limits the webhook to 5 secs. this should run async...

    """
    json_data = simplejson.loads(request.data)
    data = json_data['payload']

    if not gocardless.client.validate_webhook(data):
        logger.error("Unable to validate gocardless webhook")
        return ('', 403)

    logger.info("Webhook resource type %s action %s", data.get('resource_type'), data.get('action'))

    if data['resource_type'] != 'bill':
        logger.warn('Resource type is not bill')
        return ('', 501)

    if data['action'] not in ['paid', 'withdrawn', 'failed', 'created']:
        logger.warn('Unknown action')
        return ('', 501)

    # action can be:
    #
    # paid -> money taken from the customers account, at this point we concider the ticket paid.
    # created -> for subscriptions
    # failed -> customer is broke
    # withdrawn -> we actually get the money

    for bill in data['bills']:
        gcid = bill['id']
        try:
            payment = GoCardlessPayment.query.filter_by(gcid=gcid).one()
        except NoResultFound:
            logger.warn('Payment %s not found, ignoring', gcid)
            continue

        logger.info("Processing payment %s (%s) for user %s",
            payment.id, gcid, payment.user.id)

        if data['action'] == 'paid':
            if payment.state != "inprogress":
                logger.warning("Old payment state was %s, not 'inprogress'", payment.state)

            for t in payment.tickets.all():
                t.paid = True

            payment.state = "paid"
            db.session.commit()

            msg = Message("Your EMF ticket payment has been confirmed",
                sender=app.config['TICKETS_EMAIL'],
                recipients=[payment.user.email]
            )
            msg.body = render_template("tickets-paid-email-gocardless.txt",
                user = payment.user, payment=payment)
            mail.send(msg)

        else:
            logger.debug('Payment: %s', bill)

    return ('', 200)


