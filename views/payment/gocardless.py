from main import app, db, gocardless, mail, csrf
from models.payment import GoCardlessPayment
from views import (
    feature_flag, set_user_currency,
    add_payment_and_tickets,
)

from flask import (
    render_template, redirect, request, flash,
    url_for,
)
from flask.ext.login import login_required, current_user
from flaskext.mail import Message

from flask_wtf import Form
from wtforms.validators import Required, ValidationError
from wtforms.widgets import HiddenInput
from wtforms import SubmitField, HiddenField

import simplejson
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class GoCardlessTryAgainForm(Form):
    payment = HiddenField('payment_id', [Required()])
    pay = SubmitField('Pay')
    cancel = SubmitField('Cancel')
    yesno = HiddenField('yesno', [Required()], default="no")
    yes = SubmitField('Yes')
    no = SubmitField('No')

    def validate_payment(form, field):
        payment = None
        try:
            payment = current_user.payments.filter_by(id=int(field.data), provider="gocardless", state="new").one()
        except Exception, e:
            logger.error("Exception %r getting payment for %s", e, form.data)

        if not payment:
            raise ValidationError('Sorry, that dosn\'t look like a valid payment')


@app.route("/pay/gocardless-start", methods=['POST'])
@feature_flag('GOCARDLESS')
@login_required
def gocardless_start():
    set_user_currency('GBP')

    payment = add_payment_and_tickets(GoCardlessPayment)
    if not payment:
        flash('Your session information has been lost. Please try ordering again.')
        return redirect(url_for('tickets'))

    logger.info("New payment %s", payment.id)

    bill_url = payment.bill_url("Electromagnetic Field Tickets")

    return redirect(bill_url)

@app.route("/pay/gocardless-tryagain", methods=['POST'])
@login_required
def gocardless_tryagain():
    form = GoCardlessTryAgainForm(request.form)
    payment_id = None

    if request.method == 'POST' and form.validate():
        if form.payment:
            payment_id = int(form.payment.data)

    if not payment_id:
        flash('Unable to validate form. The web team have been notified.')
        logger.error('Invalid payment %s', payment_id)
        return redirect(url_for('tickets'))

    logging.info('Request to retry payment %s', payment_id)

    try:
        payment = current_user.payments.filter_by(id=payment_id, user=current_user, state='new').one()
    except Exception, e:
        logger.error("Exception %r getting payment", e)
        flash("An error occurred with your payment, please contact %s" % app.config['TICKETS_EMAIL'][1])
        return redirect(url_for('tickets'))

    if form.pay.data == True:
        if not config.get('GOCARDLESS'):
            logger.error('Unable to retry payment as GoCardless is disabled')
            flash('GoCardless is currently unavailable. Please try again later')
            return redirect(url_for('tickets'))

        logger.info("Trying payment %s again", payment.id)
        bill_url = payment.bill_url("Electromagnetic Field Ticket Deposit")
        return redirect(bill_url)

    if form.cancel.data == True:
        ynform = GoCardlessTryAgainForm(payment = payment.id, yesno = "yes", formdata=None)
        return render_template('gocardless-discard-yesno.html', payment=payment, form=ynform)

    if form.yes.data == True:
        for t in payment.tickets.all():
            db.session.delete(t)
            logger.info("Cancelling ticket %s", t.id)
        logger.info("Cancelled payment %s", payment.id)
        payment.state = "cancelled"
        db.session.commit()
        flash("Your GoCardless payment has been cancelled")

    return redirect(url_for('tickets'))

@app.route("/pay/gocardless-complete")
@login_required
def gocardless_complete():
    payment_id = int(request.args.get('payment'))

    logger.info("Completing payment %s, gcid %s", payment_id, request.args.get('resource_id'))

    try:
        gocardless.client.confirm_resource(request.args)

        if request.args["resource_type"] != "bill":
            raise ValueError("GoCardless resource type %s, not bill" % request.args['resource_type'])

        gcid = request.args["resource_id"]

        payment = current_user.payments.filter_by(id=payment_id).one()

    except Exception, e:
        logger.error("Exception %r confirming payment", e)
        flash("An error occurred with your payment, please contact %s" % app.config['TICKETS_EMAIL'][1])
        return redirect(url_for('tickets'))

    if payment.state != 'new':
        logger.error('Payment state is not new: %s', payment.state)
        flash('Your payment has already been confirmed, please contact %s' % app.config['TICKET_EMAIL'][1])
        return redirect(url_for('tickets'))

    # keep the gocardless reference so we can find the payment when we get called by the webhook
    payment.gcid = gcid
    payment.state = "inprogress"

    for t in payment.tickets:
        # We need to make sure of a 5 working days grace
        # for gocardless payments, so push the ticket expiry forwards
        t.expires = datetime.utcnow() + timedelta(10)
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

    return redirect(url_for('gocardless_waiting', payment=payment_id))

@app.route('/pay/gocardless-waiting')
@login_required
def gocardless_waiting():
    try:
        payment_id = int(request.args.get('payment'))
    except (TypeError, ValueError):
        logger.error("Error getting payment with args %s", request.args)
        return redirect(url_for('main'))

    try: 
        payment = current_user.payments.filter_by(id=payment_id).one()
    except NoResultFound:
        logger.error("Could not retrieve payment %s, not logged in?", payment_id)
        flash("No matching payment found for you, sorry!")
        return redirect(url_for('main'))

    return render_template('gocardless-waiting.html', payment=payment, days=app.config['EXPIRY_DAYS'])

@app.route("/pay/gocardless-cancel")
@login_required
def gocardless_cancel():
    payment_id = int(request.args.get('payment'))

    logger.info("Request to cancel payment %s", payment_id)

    try:
        payment = current_user.payments.filter_by(id=payment_id).one()

    except Exception, e:
        logger.error("Exception %r getting payment", e)
        flash("An error occurred with your payment, please contact %s" % app.config['TICKETS_EMAIL'][1])
        return redirect(url_for('tickets'))

    payment.state = 'cancelled'
    for ticket in payment.tickets:
        logger.info("Cancelling ticket %s", ticket.id)
        ticket.payment = None

    db.session.commit()

    logger.info("Payment cancellation completed OK")

    return render_template('gocardless-cancel.html', payment=payment)

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


