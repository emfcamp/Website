from main import app, db, gocardless, mail
from models.user import User
from models.payment import Payment, BankPayment, GoCardlessPayment
from models.ticket import TicketType, Ticket

from flask import \
    render_template, redirect, request, flash, \
    url_for, abort, send_from_directory, session
from flaskext.login import \
    login_user, login_required, logout_user, current_user
from flaskext.mail import Message
from flaskext.wtf import \
    Form, Required, Email, EqualTo, ValidationError, \
    TextField, PasswordField, SelectField, HiddenField, \
    SubmitField, BooleanField, IntegerField, HiddenInput, \
    DecimalField

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import text

from decorator import decorator
import simplejson, os, re
from datetime import datetime, timedelta

class IntegerSelectField(SelectField):
    def __init__(self, *args, **kwargs):
        kwargs['coerce'] = int
        self.fmt = kwargs.pop('fmt', str)
        self.values = kwargs.pop('values', [])
        SelectField.__init__(self, *args, **kwargs)

    @property
    def values(self):
        return self._values

    @values.setter
    def values(self, vals):
        self._values = vals
        self.choices = [(i, self.fmt(i)) for i in vals]

class ChoosePrepayTicketsForm(Form):
    count = IntegerSelectField('Number of tickets', [Required()])

@app.route("/tickets", methods=['GET', 'POST'])
def tickets():
    form = ChoosePrepayTicketsForm(request.form)
    form.count.values = range(1, TicketType.Prepay.limit + 1)

    if request.method == 'POST' and form.validate():
        session["count"] = form.count.data
        if current_user.is_authenticated():
            return redirect(url_for('pay_choose'))
        else:
            return redirect(url_for('signup', next=url_for('pay_choose')))

    if current_user.is_authenticated():
        tickets = current_user.tickets.all()
        payments = current_user.payments.filter(Payment.state != "canceled", Payment.state != "expired").all()
    else:
        tickets = []
        payments = []

    #
    # go through existing payments
    # and make cancel and/or pay buttons as needed.
    #
    # We don't allow canceling of inprogress gocardless payments cos there is
    # money in the system and then we have to sort out refunds etc.
    #
    # With canceled Bank Transfers we mark the payment as canceled in
    # case it does turn up for some reason and we need to do something with
    # it.
    #
    gc_try_again_forms = {}
    btcancel_forms = {}
    for p in payments:
        if p.provider == "gocardless" and p.state == "new":
            gc_try_again_forms[p.id] = GoCardlessTryAgainForm(formdata=None, payment=p.id, yesno='no')
        elif p.provider == "banktransfer" and p.state == "inprogress":
            btcancel_forms[p.id] = BankTransferCancelForm(formdata=None, payment=p.id, yesno='no')
        # the rest are inprogress or complete gocardless payments
        # or complete banktransfers,
        # or canceled payments of either provider.

    count = 1
    if "count" in session:
        count = session["count"]

    return render_template("tickets.html",
        form=form,
        tickets=tickets,
        payments=payments,
        amount=count,
        price=TicketType.Prepay.cost,
        tryagain_forms=gc_try_again_forms,
        btcancel_forms=btcancel_forms
    )

def buy_prepay_tickets(paymenttype, count):
    """
    Temporary procedure to create a payment from session data
    """
    prepays = current_user.tickets. \
        filter_by(type=TicketType.Prepay).\
        filter(Ticket.expires >= datetime.utcnow()). \
        count()
    if prepays + count > TicketType.Prepay.limit:
        raise Exception('You can only buy %s tickets in total' % TicketType.Prepay.limit)

    tickets = [Ticket(type_id=TicketType.Prepay.id) for i in range(count)]

    amount = sum(t.type.cost for t in tickets)

    payment = paymenttype(amount)
    current_user.payments.append(payment)

    for t in tickets:
        current_user.tickets.append(t)
        t.payment = payment
        t.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS'))

    db.session.add(current_user)
    db.session.commit()

    return payment


@app.route("/pay")
def pay():
    if current_user.is_authenticated():
        return redirect(url_for('pay_choose'))

    return render_template('payment-options.html')

@app.route("/pay/terms")
def ticket_terms():
    return render_template('terms.html')

@app.route("/pay/choose")
@login_required
def pay_choose():
    count = session.get('count')
    if not count:
        return redirect(url_for('tickets'))

    prepays = current_user.tickets. \
        filter_by(type=TicketType.Prepay).\
        filter(Ticket.expires >= datetime.utcnow()). \
        count()
    if count + prepays > TicketType.Prepay.limit:
        flash("You can only buy up to 4 tickets per person.")
        return redirect(url_for('tickets'))

    amount = TicketType.Prepay.cost * count

    return render_template('payment-choose.html', count=count, amount=amount)

@app.route("/pay/gocardless-start", methods=['POST'])
@login_required
def gocardless_start():
    count = session.pop('count', None)
    if not count:
        flash('Your session information has been lost. Please try ordering again.')
        return redirect(url_for('tickets'))

    payment = buy_prepay_tickets(GoCardlessPayment, count)

    app.logger.info("User %s created GoCardless payment %s", current_user.id, payment.id)

    bill_url = payment.bill_url("Electromagnetic Field Ticket Deposit")

    return redirect(bill_url)

class GoCardlessTryAgainForm(Form):
    payment = HiddenField('payment_id', [Required()])
    pay = SubmitField('Pay')
    cancel = SubmitField('Cancel & Discard tickets')
    yesno = HiddenField('yesno', [Required()], default="no")
    yes = SubmitField('Yes')
    no = SubmitField('No')

    def validate_payment(form, field):
        payment = None
        try:
            payment = current_user.payments.filter_by(id=int(field.data), provider="gocardless", state="new").one()
        except Exception, e:
            app.logger.error("GCTryAgainForm got bogus payment: %s" % (form.data))

        if not payment:
            raise ValidationError('Sorry, that dosn\'t look like a valid payment')

class BankTransferCancelForm(Form):
    payment = HiddenField('payment_id', [Required()])
    cancel = SubmitField('Cancel & Discard tickets')
    yesno = HiddenField('yesno', [Required()], default='no')
    yes = SubmitField('Yes')
    no = SubmitField('No')

    def validate_payment(form, field):
        payment = None
        try:
            payment = current_user.payments.filter_by(id=int(field.data), provider="banktransfer", state="inprogress").one()
        except Exception, e:
            app.logger.error("BankTransferCancelForm got bogus payment: %s" % (form.data))

        if not payment:
            raise ValidationError('Sorry, that dosn\'t look like a valid payment')

@app.route("/pay/gocardless-tryagain", methods=['POST'])
@login_required
def gocardless_tryagain():
    """
        If for some reason the gocardless payment didn't start properly this gives the user
        a chance to go again or to cancel the payment.
    """
    form = GoCardlessTryAgainForm(request.form)
    payment_id = None

    if request.method == 'POST' and form.validate():
        if form.payment:
            payment_id = int(form.payment.data)

    if not payment_id:
        flash('Unable to validate form, the webadmin\'s have been notified.')
        app.logger.error("gocardless-tryagain: unable to get payment_id")
        return redirect(url_for('tickets'))

    try:
        payment = current_user.payments.filter_by(id=payment_id, user=current_user, state='new').one()
    except Exception, e:
        app.logger.error("gocardless-tryagain: exception: %s for payment %d", e, payment.id)
        flash("An error occurred with your payment, please contact %s" % app.config.get('TICKETS_EMAIL')[1])
        return redirect(url_for('tickets'))

    if form.pay.data == True:
        app.logger.info("User %d trying to pay again with GoCardless payment %d", current_user.id, payment.id)
        bill_url = payment.bill_url("Electromagnetic Field Ticket Deposit")
        return redirect(bill_url)

    if form.cancel.data == True:
        ynform = GoCardlessTryAgainForm(payment = payment.id, yesno = "yes", formdata=None)
        return render_template('gocardless-discard-yesno.html', payment=payment, form=ynform)

    if form.yes.data == True:
        app.logger.info("User %d canceled new GoCardless payment %d", current_user.id, payment.id)
        for t in payment.tickets.all():
            db.session.delete(t)
            app.logger.info("Canceling Gocardless ticket %d (u:%d p:%d)", t.id, current_user.id, payment.id)
        app.logger.info("Canceling Gocardless payment %d (u:%d)", payment.id, current_user.id)
        payment.state = "canceled"
        db.session.add(payment)
        db.session.commit()
        flash("Your gocardless payment has been canceled")

    return redirect(url_for('tickets'))

@app.route("/pay/gocardless-complete")
@login_required
def gocardless_complete():
    payment_id = int(request.args.get('payment'))

    app.logger.info("gocardless-complete: userid %s, payment_id %s, gcid %s",
        current_user.id, payment_id, request.args.get('resource_id'))

    try:
        gocardless.client.confirm_resource(request.args)

        if request.args["resource_type"] != "bill":
            raise ValueError("GoCardless resource type %s, not bill" % request.args['resource_type'])

        gcid = request.args["resource_id"]

        payment = current_user.payments.filter_by(id=payment_id).one()

    except Exception, e:
        app.logger.error("gocardless-complete exception: %s", e)
        flash("An error occurred with your payment, please contact %s" % app.config.get('TICKETS_EMAIL')[1])
        return redirect(url_for('tickets'))

    # keep the gocardless reference so we can find the payment when we get called by the webhook
    payment.gcid = gcid
    payment.state = "inprogress"
    db.session.add(payment)

    for t in payment.tickets:
        # We need to make sure of a 5 working days grace
        # for gocardless payments, so push the ticket expiry forwards
        t.expires = datetime.utcnow() + timedelta(10)
        app.logger.info("ticket %d (payment %d): expiry reset.", t.id, payment.id)
        db.session.add(t)

    db.session.commit()

    app.logger.info("Payment %d completed OK", payment.id)

    # should we send the resource_uri in the bill email?
    msg = Message("Your EMF ticket purchase", \
        sender=app.config.get('TICKETS_EMAIL'),
        recipients=[payment.user.email]
    )
    msg.body = render_template("tickets-purchased-email-gocardless.txt", \
        basket={"count" : len(payment.tickets.all()), "reference" : gcid}, \
        user = payment.user, payment=payment)
    mail.send(msg)

    return redirect(url_for('gocardless_waiting', payment=payment_id))

@app.route('/pay/gocardless-waiting')
@login_required
def gocardless_waiting():
    try:
        payment_id = int(request.args.get('payment'))
    except (TypeError, ValueError):
        app.logger.error("gocardless-waiting called without a payment or with a bogus payment: %s" % (str(request.args)))
        return redirect(url_for('main'))

    try: 
        payment = current_user.payments.filter_by(id=payment_id).one()
    except NoResultFound:
        app.logger.error("someone tried to get payment %d, not logged in?" % (payment_id))
        flash("No matching payment found for you, sorry!")
        return redirect(url_for('main'))

    return render_template('gocardless-waiting.html', payment=payment, days=app.config.get('EXPIRY_DAYS'))

@app.route("/pay/gocardless-cancel")
@login_required
def gocardless_cancel():
    payment_id = int(request.args.get('payment'))

    app.logger.info("gocardless-cancel: userid %s, payment_id %s",
        current_user.id, payment_id)

    try:
        payment = current_user.payments.filter_by(id=payment_id).one()

    except Exception, e:
        app.logger.error("gocardless-cancel exception: %s", e)
        flash("An error occurred with your payment, please contact %s" % app.config.get('TICKETS_EMAIL')[1])
        return redirect(url_for('tickets'))

    for t in payment.tickets:
        app.logger.info("gocardless-cancel: userid %s, payment_id %s canceled ticket %d",
            current_user.id, payment.id, ticket.id)
        t.payment = None

    db.session.add(current_user)
    db.session.commit()

    app.logger.info("Payment cancelation completed OK")

    return render_template('gocardless-cancel.html', payment=payment)

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
        app.logger.error("unable to validate gocardless webhook")
        return ('', 403)

    app.logger.info("gocardless-webhook: %s %s", data.get('resource_type'), data.get('action'))

    if data['resource_type'] != 'bill':
        app.logger.warn('Resource type is not bill')
        return ('', 501)

    if data['action'] not in ['paid', 'withdrawn', 'failed', 'created']:
        app.logger.warn('Unknown action')
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
            app.logger.warn('Payment %s not found, ignoring', gcid)
            continue

        app.logger.info("Processing payment %s (%s) for user %s",
            payment.id, gcid, payment.user.id)

        if data['action'] == 'paid':
            if payment.state != "inprogress":
                app.logger.warning("Old payment state was %s, not 'inprogress'", payment.state)

            for t in payment.tickets.all():
                t.paid = True

            payment.state = "paid"
            db.session.add(payment)
            db.session.commit()

            msg = Message("Your EMF ticket payment has been confirmed", \
                sender=app.config.get('TICKETS_EMAIL'),
                recipients=[payment.user.email]
            )
            msg.body = render_template("tickets-paid-email-gocardless.txt", \
                basket={"count" : len(payment.tickets.all()), "reference" : gcid}, \
                user = payment.user, payment=payment)
            mail.send(msg)

        else:
            app.logger.debug('Payment: %s', bill)

    return ('', 200)


@app.route("/pay/transfer-start", methods=['POST'])
@login_required
def transfer_start():
    count = session.pop('count', None)
    if not count:
        flash('Your session information has been lost. Please try ordering again.')
        return redirect(url_for('tickets'))

    payment = buy_prepay_tickets(BankPayment, count)

    app.logger.info("User %s created bank payment %s (%s)", current_user.id, payment.id, payment.bankref)

    payment.state = "inprogress"
    db.session.add(payment)
    db.session.commit()

    msg = Message("Your EMF ticket purchase", \
        sender=app.config.get('TICKETS_EMAIL'), \
        recipients=[current_user.email]
    )
    msg.body = render_template("tickets-purchased-email-banktransfer.txt", \
        basket={"count" : len(payment.tickets.all()), "reference" : payment.bankref}, \
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
            app.logger.error("Attempt to get an inaccessible payment (%d) by user %d (%s)" % (payment_id, current_user.id, current_user.name))
        else:
            app.logger.error("Attempt to get an inaccessible payment (%d)" % (payment_id))
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
        flash('Unable to validate form, the webadmin\'s have been notified.')
        app.logger.error("transfer_cancel: unable to get payment_id")
        return redirect(url_for('tickets'))

    try:
        payment = current_user.payments.filter_by(id=payment_id, user=current_user, state='inprogress', provider='banktransfer').one()
    except Exception, e:
        app.logger.error("transfer_cancel: exception: %s for payment %d", e, payment.id)
        flash("An error occurred with your payment, please contact %s" % app.config.get('TICKETS_EMAIL')[1])
        return redirect(url_for('tickets'))

    if form.yesno.data == "no" and form.cancel.data == True:
        ynform = BankTransferCancelForm(payment=payment.id, yesno='yes', formdata=None)
        return render_template('transfer-cancel-yesno.html', payment=payment, form=ynform)

    if form.no.data == True:
        return redirect(url_for('tickets'))
    elif form.yes.data == True:
        app.logger.info("User %d canceled inprogress bank transfer %d", current_user.id, payment.id)
        for t in payment.tickets.all():
            db.session.delete(t)
            app.logger.info("Canceling bank transfer ticket %d (u:%d p:%d)", t.id, current_user.id, payment.id)
        app.logger.info("Canceling bank transfer payment %d (u:%d)", payment.id, current_user.id)
        payment.state = "canceled"
        db.session.add(payment)
        db.session.commit()
        flash('Payment cancelled')

    return redirect(url_for('tickets'))
