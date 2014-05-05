from main import (
    app, db, mail,
)
from models.payment import BankPayment
from views import feature_flag
from views.tickets import add_payment_and_tickets

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


class BankTransferCancelForm(Form):
    payment = HiddenField('payment_id', [Required()])
    cancel = SubmitField('Cancel')
    yesno = HiddenField('yesno', [Required()], default='no')
    yes = SubmitField('Yes')
    no = SubmitField('No')

    def validate_payment(form, field):
        payment = None
        try:
            payment = current_user.payments.filter_by(id=int(field.data), provider="banktransfer", state="inprogress").one()
        except Exception, e:
            app.logger.error("BankTransferCancelForm got bogus payment: %s", form.data)

        if not payment:
            raise ValidationError('Sorry, that dosn\'t look like a valid payment')


@app.route("/pay/transfer-start", methods=['POST'])
@feature_flag('BANK_TRANSFER')
@login_required
def transfer_start():
    payment = add_payment_and_tickets(BankPayment)
    if not payment:
        flash('Your session information has been lost. Please try ordering again.')
        return redirect(url_for('tickets'))

    app.logger.info("User %s created bank payment %s (%s)", current_user.id, payment.id, payment.bankref)

    payment.state = "inprogress"
    db.session.commit()

    msg = Message("Your EMF ticket purchase", \
        sender=app.config.get('TICKETS_EMAIL'), \
        recipients=[current_user.email]
    )
    msg.body = render_template("tickets-purchased-email-banktransfer.txt", \
        user = current_user, payment=payment)
    mail.send(msg)

    return redirect(url_for('transfer_waiting', payment=payment.id))

@app.route("/pay/transfer-waiting")
@login_required
def transfer_waiting():
    payment_id = int(request.args.get('payment'))
    try:
        payment = current_user.payments.filter_by(id=payment_id, user=current_user).one()
    except NoResultFound:
        if current_user:
            app.logger.error("Attempt to get an inaccessible payment (%s) by user %s", payment_id, current_user.id)
        else:
            app.logger.error("Attempt to get an inaccessible payment (%s)", payment_id)
        return redirect(url_for('tickets'))
    return render_template('transfer-waiting.html', payment=payment, days=app.config.get('EXPIRY_DAYS'))

@app.route("/pay/transfer-cancel", methods=['POST'])
@login_required
def transfer_cancel():
    """
        Cancel an existing bank transfer
    """
    form = BankTransferCancelForm(request.form)
    payment_id = None

    if request.method == 'POST' and form.validate():
        if form.payment:
            payment_id = int(form.payment.data)

    if not payment_id:
        flash('Unable to validate form. The web team have been notified.')
        app.logger.error("transfer_cancel: unable to get payment_id")
        return redirect(url_for('tickets'))

    try:
        payment = current_user.payments.filter_by(id=payment_id, user=current_user, state='inprogress', provider='banktransfer').one()
    except Exception, e:
        app.logger.error("transfer_cancel: exception: %s for payment %s", e, payment.id)
        flash("An error occurred with your payment, please contact %s" % app.config.get('TICKETS_EMAIL')[1])
        return redirect(url_for('tickets'))

    if form.yesno.data == "no" and form.cancel.data == True:
        ynform = BankTransferCancelForm(payment=payment.id, yesno='yes', formdata=None)
        return render_template('transfer-cancel-yesno.html', payment=payment, form=ynform)

    if form.no.data == True:
        return redirect(url_for('tickets'))
    elif form.yes.data == True:
        app.logger.info("User %s cancelled inprogress bank transfer %s", current_user.id, payment.id)
        for t in payment.tickets.all():
            db.session.delete(t)
            app.logger.info("Cancelling bank transfer ticket %s (u:%s p:%s)", t.id, current_user.id, payment.id)
        app.logger.info("Cancelling bank transfer payment %s (u:%s)", payment.id, current_user.id)
        payment.state = "cancelled"
        db.session.commit()
        flash('Payment cancelled')

    return redirect(url_for('tickets'))


