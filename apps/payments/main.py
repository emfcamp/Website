from flask import (
    render_template, redirect, request, flash,
    url_for, current_app as app,
)
from flask_mail import Message
from wtforms import StringField, SubmitField
from wtforms.validators import Required

from . import payments
from .common import get_user_payment_or_abort
from ..common.forms import Form
from main import db, mail
from models import RefundRequest


@payments.route('/pay/terms')
def terms():
    return render_template('terms.html')


class RefundRequestForm(Form):
    bank = StringField("Sort Code/BIC", [Required()])
    account = StringField("Account Number/IBAN", [Required()])
    submit = SubmitField('Request refund')

@payments.route('/payment/<int:payment_id>/refund', methods=['GET', 'POST'])
def payment_refund_request(payment_id):
    payment = get_user_payment_or_abort(
        payment_id,
        valid_states=['paid'],
    )

    if payment.provider == 'stripe' and not request.args.get('no_stripe'):
        return redirect(url_for('.stripe_refund_start', payment_id=payment.id))

    form = RefundRequestForm()

    if form.validate_on_submit():
        app.logger.info('Creating refund request for payment %s', payment.id)
        req = RefundRequest(payment, form.bank.data, form.account.data)
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

    return render_template('payments/refund-request.html', payment=payment, form=form)

