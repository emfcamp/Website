from main import app
from flask import render_template, redirect, url_for, abort
from models import StripePayment
from views import get_basket
from flask.ext.login import login_required, current_user

def get_user_payment_or_abort(payment_id, provider=None, valid_states=None):
    try:
        payment = current_user.payments.filter_by(id=payment_id).one()
    except Exception, e:
        app.logger.warning('Exception %r getting payment %s', e, payment_id)
        abort(404)

    if provider and payment.provider != provider:
        app.logger.warning('Payment %s is of type %s, not %s', payment.provider, provider)
        abort(404)

    if valid_states and payment.state not in valid_states:
        app.logger.warning("Payment %s is %s, not one of %s", payment_id, payment.state, valid_states)
        abort(404)

    return payment


@app.route("/pay/terms")
def ticket_terms():
    return render_template('terms.html')

@app.route("/pay/choose")
@login_required
def pay_choose():
    basket, total = get_basket()

    if not basket:
        redirect(url_for('tickets'))

    return render_template('payment-choose.html', basket=basket, total=total, StripePayment=StripePayment)

import banktransfer
import gocardless
import stripe

