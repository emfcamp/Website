from main import app, db, stripe, mail, csrf
from models.payment import StripePayment
from views import feature_flag, Form
from views.payment import get_user_payment_or_abort
from views.tickets import add_payment_and_tickets, render_receipt, render_pdf

from flask import (
    render_template, redirect, request, flash,
    url_for, abort,
)
from flask.ext.login import login_required
from flaskext.mail import Message

from wtforms import SubmitField, HiddenField

from sqlalchemy.orm.exc import NoResultFound

import simplejson
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class StripeUpdateUnexpected(Exception):
    pass

class StripeUpdateConflict(Exception):
    pass

webhook_handlers = {}
def webhook(type=None):
    def inner(f):
        webhook_handlers[type] = f
        return f
    return inner

@app.route("/pay/stripe-start", methods=['POST'])
@feature_flag('STRIPE')
@login_required
def stripe_start():
    payment = add_payment_and_tickets(StripePayment)
    if not payment:
        logger.warn('Unable to add payment and tickets to database')
        flash('Your session information has been lost. Please try ordering again.')
        return redirect(url_for('tickets'))

    logger.info("Created Stripe payment %s", payment.id)
    db.session.commit()

    return redirect(url_for('stripe_capture', payment_id=payment.id))


def charge_stripe(payment):
    logger.info("Charging Stripe payment %s, token %s", payment.id, payment.token)
    try:
        charge = stripe.Charge.create(
            amount=payment.amount_int,
            currency=payment.currency.lower(),
            card=payment.token,
            description=payment.description,
            statement_description='Tickets 2014', # max 15 chars, appended to company name
        )

    except stripe.CardError, e:
        logger.warn('Card payment failed with exception "%s"', e)
        # Don't save the charge_id - they can try again
        flash('An error occurred with your payment, please try again')
        return redirect(url_for('stripe_tryagain', payment_id=payment.id))

    except Exception, e:
        logger.warn("Exception %r confirming payment", e)
        flash('An error occurred with your payment, please try again')
        return redirect(url_for('stripe_tryagain', payment_id=payment.id))

    payment.chargeid = charge.id
    if charge.paid:
        payment.paid()
    else:
        payment.state = 'charged'

        for t in payment.tickets:
            t.expires = datetime.utcnow() + timedelta(days=app.config['EXPIRY_DAYS_STRIPE'])
            logger.info("Set expiry for ticket %s", t.id)

    db.session.commit()

    logger.info('Payment %s completed OK (state %s)', payment.id, payment.state)

    msg = Message("Your EMF ticket purchase",
        sender=app.config.get('TICKETS_EMAIL'),
        recipients=[payment.user.email])
    msg.body = render_template("tickets-purchased-email-stripe.txt",
        user=payment.user, payment=payment)

    if app.config.get('RECEIPTS'):
        page = render_receipt(payment.tickets, pdf=True)
        pdf = render_pdf(page)
        msg.attach('Receipt.pdf', 'application/pdf', pdf.read())

    mail.send(msg)

    return redirect(url_for('stripe_waiting', payment_id=payment.id))


class StripeAuthorizeForm(Form):
    token = HiddenField('Stripe token')
    forward = SubmitField('Continue')

@app.route("/pay/stripe/<int:payment_id>/capture", methods=['GET', 'POST'])
@login_required
def stripe_capture(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'stripe',
        valid_states=['new'],
    )

    if not app.config.get('STRIPE'):
        logger.warn('Unable to capture payment as Stripe is disabled')
        flash('Stripe is currently unavailable. Please try again later')
        return redirect(url_for('tickets'))

    form = StripeAuthorizeForm(request.form)
    if form.validate_on_submit():
        try:
            logger.info("Stripe payment %s captured, token %s", payment.id, payment.token)
            payment.token = form.token.data
            payment.state = 'captured'
            db.session.commit()

        except Exception, e:
            logger.warn("Exception %r updating payment", e)
            flash('An error occurred with your payment, please try again')
            return redirect(url_for('stripe_tryagain', payment_id=payment.id))

        return charge_stripe(payment)

    logger.info("Trying to check out payment %s", payment.id)
    return render_template('stripe-checkout.html', payment=payment, form=form)

class StripeChargeAgainForm(Form):
    tryagain = SubmitField('Try again')

@app.route("/pay/stripe/<int:payment_id>/tryagain", methods=['GET', 'POST'])
@login_required
def stripe_tryagain(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'stripe',
        valid_states=['new', 'captured'], # once it's charged it's too late
    )

    if not app.config.get('STRIPE'):
        logger.warn('Unable to retry payment as Stripe is disabled')
        flash('Stripe is currently unavailable. Please try again later')
        return redirect(url_for('tickets'))

    if payment.state == 'new':
        return redirect(url_for('stripe_capture', payment_id=payment.id))

    form = StripeChargeAgainForm()
    if form.validate_on_submit():
        logger.info("Trying to charge payment %s again", payment.id)
        return charge_stripe(payment)

    return render_template('stripe-tryagain.html', payment=payment, form=form)


class StripeCancelForm(Form):
    yes = SubmitField('Cancel payment')

@app.route("/pay/stripe/<int:payment_id>/cancel", methods=['GET', 'POST'])
@login_required
def stripe_cancel(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'stripe',
        valid_states=['new', 'captured'],
    )

    form = StripeCancelForm(request.form)
    if form.validate_on_submit():
        if form.yes.data:
            logger.info('Cancelling Stripe payment %s', payment.id)
            payment.cancel()
            db.session.commit()

            if payment.token:
                logger.warn('Stripe payment has outstanding token %s', payment.token)

            logger.info('Payment %s cancelled', payment.id)
            flash('Payment cancelled')

        return redirect(url_for('tickets'))

    return render_template('stripe-cancel.html', payment=payment, form=form)

@app.route('/pay/stripe/<int:payment_id>/waiting')
@login_required
def stripe_waiting(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, 'stripe',
        valid_states=['charged', 'paid'],
    )
    return render_template('stripe-waiting.html', payment=payment, days=app.config['EXPIRY_DAYS_STRIPE'])


@csrf.exempt
@app.route("/stripe-webhook", methods=['POST'])
def stripe_webhook():
    logger.debug('Stripe webhook called with %s', request.data)
    json_data = simplejson.loads(request.data)

    try:
        if json_data['object'] != 'event':
            logger.warning('Unrecognised callback object: %s', json_data['object'])
            abort(501)

        livemode = not app.config.get('DEBUG')
        if json_data['livemode'] != livemode:
            logger.error('Unexpected livemode status %s, failing', json_data['livemode'])
            abort(409)

        obj_data = json_data['data']['object']
        type = json_data['type']
        try:
            handler = webhook_handlers[type]
        except KeyError, e:
            handler = webhook_handlers[None]

        return handler(type, obj_data)

    except Exception, e:
        logger.error('Unexcepted exception during webhook: %r', e)
        abort(500)


@webhook()
def stripe_default(type, obj_data):
    # We can fetch events with Event.all for 30 days
    logger.warn('Default handler called for %s: %s', type, obj_data)
    return ('', 200)

@webhook('ping')
def stripe_ping(type, ping_data):
    return ('', 200)

def get_payment_or_abort(charge_id):
    try:
        return StripePayment.query.filter_by(chargeid=charge_id).one()
    except NoResultFound:
        logger.error('Payment for charge %s not found', charge_id)
        abort(409)

def stripe_update_payment(payment):
    charge = stripe.Charge.retrieve(payment.chargeid)
    if charge.refunded:
        return stripe_payment_refunded(payment)

    elif charge.paid:
        return stripe_payment_paid(payment)

    app.logger.error('Charge object is not paid or refunded')
    raise StripeUpdateUnexpected()

def stripe_payment_paid(payment):
    if payment.state == 'paid':
        logger.info('Payment is already paid, ignoring')
        return

    if payment.state != 'charged':
        logger.error('Current payment state is %s (should be charged)', payment.state)
        raise StripeUpdateConflict()

    logger.info('Setting payment %s to paid', payment.id)
    payment.paid()
    db.session.commit()

    msg = Message('Your EMF ticket payment has been confirmed',
        sender=app.config.get('TICKETS_EMAIL'),
        recipients=[payment.user.email])
    msg.body = render_template('tickets-paid-email-stripe.txt',
        user=payment.user, payment=payment)

    if app.config.get('RECEIPTS'):
        page = render_receipt(payment.tickets, pdf=True)
        pdf = render_pdf(page)
        msg.attach('Receipt.pdf', 'application/pdf', pdf.read())

    mail.send(msg)

def stripe_payment_refunded(payment):
    if payment.state == 'cancelled':
        logger.info('Payment is already cancelled, ignoring')
        return

    logger.info('Setting payment %s to cancelled', payment.id)
    payment.cancel()
    db.session.commit()

    if not app.config.get('TICKETS_NOTICE_EMAIL'):
        app.logger.warning('No tickets notice email configured, not sending')
        return

    msg = Message('An EMF ticket payment has been refunded',
        sender=app.config.get('TICKETS_EMAIL'),
        recipients=[app.config.get('TICKETS_NOTICE_EMAIL')[1]])
    msg.body = render_template('tickets-refunded-email-stripe.txt',
        user=payment.user, payment=payment)
    mail.send(msg)


@webhook('charge.succeeded')
@webhook('charge.refunded')
@webhook('charge.updated')
def stripe_charge_updated(type, charge_data):
    payment = get_payment_or_abort(charge_data['id'])

    logger.info('Received %s message for charge %s, payment %s', type, charge_data['id'], payment.id)

    try:
        stripe_update_payment(payment)
    except StripeUpdateConflict:
        abort(409)
    except StripeUpdateUnexpected:
        abort(501)

    return ('', 200)

@webhook('charge.failed')
def stripe_charge_failed(type, charge_data):
    # Test with 4000 0000 0000 0341
    try:
        payment = StripePayment.query.filter_by(chargeid=charge_data['id']).one()
    except NoResultFound:
        logger.warn('Payment for failed charge %s not found, ignoring', charge_data['id'])
        return ('', 200)

    logger.info('Received failed message for charge %s, payment %s', charge_data['id'], payment.id)

    charge = stripe.Charge.retrieve(charge_data['id'])
    if not charge.failed:
        logger.error('Charge object is not failed')
        abort(501)

    if charge.paid:
        logger.error('Charge object has already been paid')
        abort(501)

    # Payment can still be retried with a new charge - nothing to do
    return ('', 200)

@webhook('charge.dispute.created')
@webhook('charge.dispute.updated')
@webhook('charge.dispute.closed')
def stripe_dispute_update(type, dispute_data):
    payment = get_payment_or_abort(dispute_data['charge'])
    logger.critical('Unexpected charge dispute event %s for payment %s: %s', type, payment.id, dispute_data)

    # Don't block other events
    return ('', 200)

