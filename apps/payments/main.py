from flask import (
    render_template, redirect, request, flash,
    url_for, current_app as app,
)
from flask_login import login_required
from flask_mail import Message
from wtforms import StringField, SubmitField
from wtforms.validators import ValidationError
import gocardless_pro.errors

from . import payments
from .common import get_user_payment_or_abort
from ..common import feature_flag
from ..common.forms import Form
from main import db, mail, gocardless_client
from models import RefundRequest


@payments.route('/pay/terms')
def terms():
    return render_template('terms.html')


def required_for(currency):
    def validate(form, field):
        if form._currency != currency:
            return
        if not field.data:
            raise ValidationError("This field is required")
    return validate

class RefundRequestForm(Form):
    # https://developer.gocardless.com/api-reference/#appendix-local-bank-details
    # We only support UK and international (Euros)
    bank = StringField("Sort Code", [required_for('GBP')])
    account = StringField("Account Number", [required_for('GBP')])
    iban = StringField("IBAN", [required_for('EUR')])
    submit = SubmitField("Request refund")
    really_submit = SubmitField("These details are correct")


@payments.route('/payment/<int:payment_id>/refund', methods=['GET', 'POST'])
@payments.route('/payment/<int:payment_id>/refund/<currency>', methods=['GET', 'POST'])
@login_required
@feature_flag('REFUND_REQUESTS')
def payment_refund_request(payment_id, currency='GBP'):
    payment = get_user_payment_or_abort(
        payment_id,
        valid_states=['paid'],
    )

    no_stripe = 'no_stripe' in request.args
    if payment.provider == 'stripe' and not no_stripe:
        return redirect(url_for('.stripe_refund_start', payment_id=payment.id))

    form = RefundRequestForm()
    form._currency = currency

    bank_validation_failed = False

    if form.validate_on_submit():
        app.logger.info("Validating bank details")
        if currency == 'GBP':
            params = {
                'country_code': 'GB',
                'branch_code': form.bank.data,
                'account_number': form.account.data
            }
        elif currency == 'EUR':
            params = {'iban': form.iban.data}

        try:
            result = gocardless_client.bank_details_lookups.create(params)
            app.logger.info("Bank identified as %r", result.attributes.get('bank_name'))

        except gocardless_pro.errors.ValidationFailedError as e:
            app.logger.warn("Error validating bank details: %s", e)
            if not form.really_submit.data:
                msg = "This doesn't look right. Please check and click below if you're sure."
                bank_validation_failed = True
                form.bank.errors.append(msg)
                form.account.errors.append(msg)
                form.iban.errors.append(msg)

        if not bank_validation_failed:
            app.logger.info('Creating refund request for payment %s', payment.id)
            if currency == 'GBP':
                account = form.account.data
            elif currency == 'EUR':
                account = form.iban.data

            req = RefundRequest(payment, currency, form.bank.data, account)
            db.session.add(req)
            payment.state = 'refund-requested'

            if not app.config.get('TICKETS_NOTICE_EMAIL'):
                app.logger.warning('No tickets notice email configured, not sending')

            else:
                msg = Message("An EMF refund request has been received",
                              sender=app.config.get('TICKETS_EMAIL'),
                              recipients=[app.config.get('TICKETS_NOTICE_EMAIL')[1]])
                msg.body = render_template('emails/notice-refund-request.txt', payment=payment)
                mail.send(msg)

            db.session.commit()

            flash("Your refund request has been sent")
            return redirect(url_for('users.purchases'))

    return render_template('payments/refund-request.html', payment=payment,
                           form=form, currency=currency, no_stripe=no_stripe,
                           bank_validation_failed=bank_validation_failed)

