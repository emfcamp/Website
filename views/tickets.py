from main import app, db, gocardless, mail
from views import feature_flag
from models.user import User
from models.payment import Payment, \
    BankPayment, GoCardlessPayment, GoogleCheckoutPayment
from models.ticket import TicketType, Ticket, TicketAttrib, TicketToken

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
    DecimalField, FieldList, FormField, Optional

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import text

from decorator import decorator
from wtforms.fields.core import UnboundField

import simplejson, os, re
from datetime import datetime, timedelta
import requests
from lxml import objectify
from base64 import b64encode
from decimal import Decimal, ROUND_UP

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


class HiddenIntegerField(HiddenField, IntegerField):
    """
    widget=HiddenInput() doesn't work with WTF-Flask's hidden_tag()
    """


class TicketForm(Form):
    ticket_id = HiddenIntegerField('Ticket Type', [Required()])

class FullTicketForm(TicketForm):
    template= 'tickets/full.html'
    volunteer = BooleanField('Volunteering')
    accessible = BooleanField('Accessibility')

class KidsTicketForm(TicketForm):
    template= 'tickets/kids.html'
    accessible = BooleanField('Accessibility')

class CarparkTicketForm(TicketForm):
    template= 'tickets/carpark.html'
    carshare = BooleanField('Car share')

class CampervanTicketForm(TicketForm):
    pass
    # XXX do we need a template for these?
    # maybe info on where to go?
#    template= 'tickets/campervan.html'

class DonationTicketForm(TicketForm):
    template= 'tickets/donation.html'
    amount = DecimalField('Donation amount')

ticket_forms = ['full', 'kids']

def get_form_name(ticket_type):
    code, _, subcode = ticket_type.code.partition('_')
    if code not in ticket_forms:
        return None
    return code

class GoogleCheckout(object):
    schema = '{http://checkout.google.com/schema/2}'
    api = 'api/checkout/v2'
    mime = 'application/xml; charset=UTF-8'
    base = app.config.get('GOOGLE_CHECKOUT_BASE')
    merchant_id = app.config.get('GOOGLE_MERCHANT_ID')
    merchant_key = app.config.get('GOOGLE_MERCHANT_KEY')

    def api_url(self, feature):
        return '/'.join([
            self.base, self.api, feature,
            'Merchant', self.merchant_id,
        ])

    def api_request(self, feature, data):
      auth = self.merchant_id, self.merchant_key
      headers = {'Content-Type': self.mime, 'Accept': self.mime}
      url = self.api_url(feature)
      return requests.post(url, auth=auth, headers=headers, data=data)

    def check_auth(self, request):
      auth = self.merchant_id, self.merchant_key
      header = 'Basic %s' % b64encode(':'.join(auth))
      return request.headers['Authorization'] == header

GCO = GoogleCheckout()


class UpdateTicketForm(Form):
    pass

class UpdateTicketsForm(Form):
    tickets = FieldList(FormField(UpdateTicketForm))

class ChoosePrepayTicketsForm(Form):
    count = IntegerSelectField('Number of tickets', [Required()])

@app.route("/tickets", methods=['GET', 'POST'])
def tickets():

    if app.config.get('FULL_TICKETS', False):
        if not (current_user.is_authenticated() and current_user.tickets.count()):
            return redirect(url_for('tickets_choose'))

    form = ChoosePrepayTicketsForm(request.form)
    form.count.values = range(1, TicketType.Prepay.limit + 1)

    if request.method == 'POST' and form.validate():
        session['basket'] = [TicketType.Prepay.id] * form.count.data

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
    retrycancel_forms = {}
    for p in payments:
        if p.provider == "gocardless" and p.state == "new":
            retrycancel_forms[p.id] = GoCardlessTryAgainForm(formdata=None, payment=p.id, yesno='no')
        if p.provider == "googlecheckout" and p.state == "new":
            retrycancel_forms[p.id] = GoogleCheckoutTryAgainForm(formdata=None, payment=p.id, yesno='no')
        elif p.provider == "banktransfer" and p.state == "inprogress":
            retrycancel_forms[p.id] = BankTransferCancelForm(formdata=None, payment=p.id, yesno='no')
        # the rest are inprogress or complete gocardless payments
        # or complete banktransfers,
        # or canceled payments of either provider.

    return render_template("tickets.html",
        form=form,
        tickets=tickets,
        payments=payments,
        price=TicketType.Prepay.cost,
        retrycancel_forms=retrycancel_forms,
    )


def add_payment_and_tickets(paymenttype):
    """
    Insert payment and tickets from session data into DB
    """

    infodata = session.get('ticketinfo')
    basket, total = get_basket()

    if not (basket and total):
        return None

    if paymenttype == GoogleCheckoutPayment:
        total *= Decimal('1.05')
        total = total.quantize(Decimal('0.01'), rounding=ROUND_UP)

    app.logger.info('Creating tickets for basket %s', basket)
    app.logger.info('Payment: %s for total %s GBP', paymenttype.name, total)
    app.logger.info('Ticket info: %s', infodata)

    if infodata:
        infolists = sum([infodata[i] for i in ticket_forms], [])
        for info in infolists:
            ticket_id = int(info.pop('ticket_id'))
            ticket = basket[ticket_id]
            for k, v in info.items():
                attrib = TicketAttrib(k, v)
                ticket.attribs.append(attrib)

    payment = paymenttype(total)
    current_user.payments.append(payment)

    for ticket in basket:
        name = get_form_name(ticket.type)
        if name and not ticket.attribs:
            app.logger.error('Ticket %s has no attribs', ticket)
            return None

        current_user.tickets.append(ticket)
        ticket.payment = payment
        if session.get('currency', 'GBP') == 'GBP':
            ticket.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS'))
        else:
            ticket.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS_EURO'))

    db.session.add(current_user)
    db.session.commit()

    session.pop('basket', None)
    session.pop('ticketinfo', None)

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

    return render_template('payment-choose.html', basket=basket, total=total, GCO=GCO)

@app.route("/pay/gocardless-start", methods=['POST'])
@login_required
def gocardless_start():
    session['currency'] = 'GBP'

    payment = add_payment_and_tickets(GoCardlessPayment)
    if not payment:
        flash('Your session information has been lost. Please try ordering again.')
        return redirect(url_for('tickets'))

    app.logger.info("User %s created GoCardless payment %s", current_user.id, payment.id)

    bill_url = payment.bill_url("Electromagnetic Field Tickets")

    return redirect(bill_url)

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
            app.logger.error("GCTryAgainForm got bogus payment: %s", form.data)

        if not payment:
            raise ValidationError('Sorry, that dosn\'t look like a valid payment')

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
        flash('Unable to validate form. The web team have been notified.')
        app.logger.error("gocardless-tryagain: unable to get payment_id")
        return redirect(url_for('tickets'))

    try:
        payment = current_user.payments.filter_by(id=payment_id, user=current_user, state='new').one()
    except Exception, e:
        app.logger.error("gocardless-tryagain: exception: %s for payment %s", e, payment.id)
        flash("An error occurred with your payment, please contact %s" % app.config.get('TICKETS_EMAIL')[1])
        return redirect(url_for('tickets'))

    if form.pay.data == True:
        app.logger.info("User %s trying to pay again with GoCardless payment %s", current_user.id, payment.id)
        bill_url = payment.bill_url("Electromagnetic Field Ticket Deposit")
        return redirect(bill_url)

    if form.cancel.data == True:
        ynform = GoCardlessTryAgainForm(payment = payment.id, yesno = "yes", formdata=None)
        return render_template('gocardless-discard-yesno.html', payment=payment, form=ynform)

    if form.yes.data == True:
        app.logger.info("User %s canceled new GoCardless payment %s", current_user.id, payment.id)
        for t in payment.tickets.all():
            db.session.delete(t)
            app.logger.info("Canceling Gocardless ticket %s (u:%s p:%s)", t.id, current_user.id, payment.id)
        app.logger.info("Canceling Gocardless payment %s (u:%s)", payment.id, current_user.id)
        payment.state = "canceled"
        db.session.add(payment)
        db.session.commit()
        flash("Your gocardless payment has been cancelled")

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
        app.logger.info("ticket %s (payment %s): expiry reset.", t.id, payment.id)
        db.session.add(t)

    db.session.commit()

    app.logger.info("Payment %s completed OK", payment.id)

    # should we send the resource_uri in the bill email?
    msg = Message("Your EMF ticket purchase", \
        sender=app.config.get('TICKETS_EMAIL'),
        recipients=[payment.user.email]
    )
    msg.body = render_template("tickets-purchased-email-gocardless.txt", \
        user = payment.user, payment=payment)
    mail.send(msg)

    return redirect(url_for('gocardless_waiting', payment=payment_id))

@app.route('/pay/gocardless-waiting')
@login_required
def gocardless_waiting():
    try:
        payment_id = int(request.args.get('payment'))
    except (TypeError, ValueError):
        app.logger.error("gocardless-waiting called without a payment or with a bogus payment: %s", request.args)
        return redirect(url_for('main'))

    try: 
        payment = current_user.payments.filter_by(id=payment_id).one()
    except NoResultFound:
        app.logger.error("someone tried to get payment %s, not logged in?", payment_id)
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

    payment.state = 'canceled'
    for ticket in payment.tickets:
        app.logger.info("gocardless-cancel: userid %s, payment_id %s canceled ticket %s",
            current_user.id, payment.id, ticket.id)
        ticket.payment = None

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
                user = payment.user, payment=payment)
            mail.send(msg)

        else:
            app.logger.debug('Payment: %s', bill)

    return ('', 200)


@app.route("/pay/transfer-start", methods=['POST'])
@login_required
def transfer_start():
    payment = add_payment_and_tickets(BankPayment)
    if not payment:
        flash('Your session information has been lost. Please try ordering again.')
        return redirect(url_for('tickets'))

    app.logger.info("User %s created bank payment %s (%s)", current_user.id, payment.id, payment.bankref)

    payment.state = "inprogress"
    db.session.add(payment)
    db.session.commit()

    msg = Message("Your EMF ticket purchase", \
        sender=app.config.get('TICKETS_EMAIL'), \
        recipients=[current_user.email]
    )
    msg.body = render_template("tickets-purchased-email-banktransfer.txt", \
        user = current_user, payment=payment)
    mail.send(msg)

    return redirect(url_for('transfer_waiting', payment=payment.id))

@app.route("/tickets/token/<token>")
def tickets_token(token):
    if TicketToken.types(token):
        session['ticket_token'] = token
    else:
        flash('Ticket token was invalid')

    return redirect(url_for('tickets_choose'))


class TicketAmountForm(Form):
    amount = IntegerSelectField('Number of tickets', [Optional()])
    type_id = HiddenIntegerField('Ticket Type', [Required()])

class TicketAmountsForm(Form):
    types = FieldList(FormField(TicketAmountForm))
    choose = SubmitField('Buy Tickets')

@app.route("/tickets/choose", methods=['GET', 'POST'])
@feature_flag('FULL_TICKETS')
def tickets_choose():
    form = TicketAmountsForm(request.form)

    if not form.types:
        for tt in TicketType.query.order_by(TicketType.order).all():
            form.types.append_entry()
            form.types[-1].type_id.data = tt.id

    if current_user.is_authenticated():
        prepays = current_user.tickets. \
            filter_by(type=TicketType.bycode('prepay'), paid=True). \
            count()
        fulls = current_user.tickets.join(TicketType). \
            filter(TicketType.code.like('full%')). \
            count()
        if fulls >= prepays:
            prepays = 0
    else:
        prepays = 0
        fulls = 0

    token_tts = TicketToken.types(session.get('ticket_token'))
    token_only = ['full_ucl', 'full_hs', 'full_make', 'full_adafruit', 'full_hackaday', 'full_boingboing']

    for f in form.types:
        tt = TicketType.query.get(f.type_id.data)
        f._type = tt

        limit = tt.user_limit(current_user)

        values = range(limit + 1)
        if tt.code == 'prepay':
            values = []
        elif tt.code == 'full_prepay':
            assert prepays <= limit
            values = [prepays]
        elif tt.code in token_only and tt not in token_tts:
            values = []
        elif tt.code == 'full':
            if token_tts:
                values = []

        f.amount.values = values
        f._any = any(values)


    if request.method == 'POST' and form.validate():

        basket = []
        for f in form.types:
            if f.amount.data:
                tt = f._type

                if tt.code in token_only and tt not in token_tts:
                    if f.amount.data:
                        flash('Ticket type %s is not currently available')
                    return redirect(url_for('tickets_choose'))

                app.logger.info('Adding %s %s tickets to basket', f.amount.data, tt.name)
                basket += [tt.id] * f.amount.data

        if basket:
            session['basket'] = basket

            if current_user.is_authenticated():
                return redirect(url_for('tickets_info'))
            else:
                return redirect(url_for('signup', next=url_for('tickets_info')))

    return render_template("tickets-choose.html", form=form)

class TicketInfoForm(Form):
    full = FieldList(FormField(FullTicketForm))
    kids = FieldList(FormField(KidsTicketForm))
    carpark = FieldList(FormField(CarparkTicketForm))
    campervan = FieldList(FormField(CampervanTicketForm))
    donation = FieldList(FormField(DonationTicketForm))
    submit = SubmitField('Continue to Check-out')
    back = SubmitField('Change tickets')

def get_basket():
    basket = []
    for type_id in session.get('basket', []):
        basket.append(Ticket(type_id=type_id))

    total = sum(t.type.get_price(session.get('currency', 'GBP')) for t in basket)

    return basket, total

def build_info_form(formdata):
    basket, total = get_basket()

    if not basket:
        return None, basket, total

    form = TicketInfoForm(formdata)

    forms = [getattr(form, f) for f in ticket_forms]

    if not any(forms):

        for i, ticket in enumerate(basket):
            name = get_form_name(ticket.type)
            if not name:
                continue

            f = getattr(form, name)
            f.append_entry()
            ticket.form = f[-1]
            ticket.form.ticket_id.data = i

        if not any(forms):
            return None, basket, total

    else:
        # FIXME: plays badly with multiple tabs
        form_tickets = [t for t in basket if get_form_name(t.type)]
        entries = sum([f.entries for f in forms], [])
        for ticket, subform in zip(form_tickets, entries):
            ticket.form = subform

    return form, basket, total

@app.route("/tickets/info", methods=['GET', 'POST'])
@feature_flag('FULL_TICKETS')
@login_required
def tickets_info():
    basket, total = get_basket()

    if not basket:
        redirect(url_for('tickets'))

    form, basket, total = build_info_form(request.form)
    if not form:
        return redirect(url_for('pay_choose'))

    if request.method == 'POST' and form.validate():
        if form.back.data:
            return redirect(url_for('tickets_choose'))

        session['ticketinfo'] = form.data

        return redirect(url_for('pay_choose'))

    return render_template('tickets-info.html', form=form, basket=basket, total=total)


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
        app.logger.info("User %s canceled inprogress bank transfer %s", current_user.id, payment.id)
        for t in payment.tickets.all():
            db.session.delete(t)
            app.logger.info("Canceling bank transfer ticket %s (u:%s p:%s)", t.id, current_user.id, payment.id)
        app.logger.info("Canceling bank transfer payment %s (u:%s)", payment.id, current_user.id)
        payment.state = "canceled"
        db.session.add(payment)
        db.session.commit()
        flash('Payment cancelled')

    return redirect(url_for('tickets'))

@app.route("/pay/google-checkout-start", methods=['POST'])
@feature_flag('GOOGLE_CHECKOUT')
@login_required
def googlecheckout_start():
    session['currency'] = 'GBP'

    basket, total = get_basket()
    payment = add_payment_and_tickets(GoogleCheckoutPayment)
    if not payment:
        flash('Your session information has been lost. Please try ordering again.')
        return redirect(url_for('tickets'))

    app.logger.info("User %s created GoCardless payment %s", current_user.id, payment.id)
    return googlecheckout_send(payment, total)

def googlecheckout_send(payment, total):
    data = render_template('google-checkout/cart.xml', payment=payment, total=total, GCO=GCO)
    data = data.encode('utf-8')
    app.logger.debug('Sending to checkout: %s', data)

    r = GCO.api_request('merchantCheckout', data)
    data = r.text.encode('utf-8')
    app.logger.debug('Response from checkout: %s', data)

    root = objectify.fromstring(data)
    if root.tag == GCO.schema + 'error':
        app.logger.error('Error creating order: %s', root['error-message'])
        flash('An error was returned from Google Checkout.')
        return redirect(url_for('tickets'))

    if root.tag != GCO.schema + 'checkout-redirect':
        flash('An invalid response was received from Google Checkout.')
        return redirect(url_for('tickets'))

    url = root['redirect-url']
    app.logger.info('Redirect URL: %s', url)

    return redirect(str(url))


class GoogleCheckoutTryAgainForm(Form):
    payment = HiddenField('payment_id', [Required()])
    pay = SubmitField('Pay')
    cancel = SubmitField('Cancel')
    yesno = HiddenField('yesno', [Required()], default="no")
    yes = SubmitField('Yes')
    no = SubmitField('No')

    def validate_payment(form, field):
        payment = None
        try:
            payment = current_user.payments.filter_by(id=int(field.data), provider="googlecheckout", state="new").one()
        except Exception, e:
            app.logger.error("GCOTryAgainForm got bogus payment: %s", form.data)

        if not payment:
            raise ValidationError('Sorry, that dosn\'t look like a valid payment')


@app.route("/pay/google-checkout-tryagain", methods=['POST'])
@login_required
def googlecheckout_tryagain():
    form = GoogleCheckoutTryAgainForm(request.form)
    payment_id = None

    if request.method == 'POST' and form.validate():
        if form.payment:
            payment_id = int(form.payment.data)

    if not payment_id:
        flash('Unable to validate form. The web team have been notified.')
        app.logger.error("google-checkout-tryagain: unable to get payment_id")
        return redirect(url_for('tickets'))

    try:
        payment = current_user.payments.filter_by(id=payment_id, user=current_user, state='new').one()
    except Exception, e:
        app.logger.error("google-checkout-tryagain: exception: %s for payment %s", e, payment.id)
        flash("An error occurred with your payment, please contact %s" % app.config.get('TICKETS_EMAIL')[1])
        return redirect(url_for('tickets'))

    if form.pay.data == True:
        if not config.get('GOOGLE_CHECKOUT'):
            app.logger.error('Unable to retry payment as Google Checkout is disabled')
            flash('Google Checkout is currently unavailable. Please try again later.')
            return redirect(url_for('tickets'))

        app.logger.info("User %s trying to pay again with Google Checkout payment %s", current_user.id, payment.id)
        total = sum(t.type.get_price(session.get('currency', 'GBP')) for t in payment.tickets)
        return googlecheckout_send(payment, total)

    if form.cancel.data == True:
        ynform = GoogleCheckoutTryAgainForm(payment=payment.id, yesno="yes", formdata=None)
        return render_template('google-checkout-discard-yesno.html', payment=payment, form=ynform)

    if form.yes.data == True:
        app.logger.info("User %s canceled new Google Checkout payment %s", current_user.id, payment.id)
        for t in payment.tickets.all():
            db.session.delete(t)
            app.logger.info("Cancelling Google Checkout ticket %s (u:%s p:%s)", t.id, current_user.id, payment.id)
        app.logger.info("Cancelling Google Checkout payment %s (u:%s)", payment.id, current_user.id)
        payment.state = "canceled"
        db.session.add(payment)
        db.session.commit()
        flash("Your Google Checkout payment has been cancelled")

    return redirect(url_for('tickets'))


@app.route("/pay/google-checkout-notify", methods=['POST'])
def googlecheckout_notify():
    if not GCO.check_auth(request):
        return ('', 401)

    if request.headers['content-type'] != GCO.mime:
        return ('', 400)

    app.logger.debug('Google Checkout notification: %s', request.data)
    root = objectify.fromstring(request.data)

    serial = root.get('serial-number')
    app.logger.info('Google checkout notification: %s', serial)

    if root.tag == GCO.schema + 'new-order-notification':
        payment_id = root['shopping-cart']['merchant-private-data']['payment-id']
        adjustment_total = root['order-adjustment']['adjustment-total']
        order_total = root['order-total']

        total = Decimal(str(order_total))
        total_currency = order_total.get('currency')
        adjustment = Decimal(str(adjustment_total))
        app.logger.info('Payment is for %s %s (adjustment %s)', total, total_currency, adjustment)

        p = GoogleCheckoutPayment.query.filter_by(id=int(payment_id)).one()
        if total != p.amount or total_currency != 'GBP':
            app.logger.error('Invalid payment amount (expected %s)', p.amount)
            raise Exception('Invalid payment amount')

        order_no = root['google-order-number']
        buyer_id = root['buyer-id']
        finance_state = root['financial-order-state']
        fulfill_state = root['fulfillment-order-state']
        email_allowed = root['buyer-marketing-preferences']['email-allowed']

        p.finance_state = str(finance_state)
        p.fulfill_state = str(fulfill_state)
        p.order_no = str(order_no)
        p.buyer_id = str(buyer_id)
        p.email_allowed = email_allowed.text == 'true'
        p.state = 'reviewing'
        db.session.commit()

        # Don't spam the user - they've already received an email from Google, and clearance should be soon

        app.logger.info('Identified order %s from %s as %s, finance %s fulfill %s',
            p.order_no, p.buyer_id, p.id, finance_state, fulfill_state)

    elif root.tag == GCO.schema + 'order-state-change-notification':
        order_no = root['google-order-number']
        p = GoogleCheckoutPayment.query.filter_by(order_no=str(order_no)).one()

        finance_state = root['new-financial-order-state']
        fulfill_state = root['new-fulfillment-order-state']
        app.logger.info('State change for payment %s: finance %s->%s fulfill %s->%s',
            p.id, p.finance_state, finance_state, p.fulfill_state, fulfill_state)

        if p.state in ('new', 'reviewing') and finance_state == 'CHARGEABLE' and p.finance_state == 'REVIEWING':
            # We've got the necessary info from Google, so let's actually charge the user

            p.state = 'charging'
            db.session.commit()

            data = render_template('google-checkout/charge-and-ship-order.xml', order_no=p.order_no)
            data = data.encode('utf-8')
            app.logger.debug('Sending to checkout: %s', data)

            r = GCO.api_request('request', data)
            data = r.text.encode('utf-8')
            app.logger.debug('Response from checkout: %s', data)

            root = objectify.fromstring(data)
            if root.tag == GCO.schema + 'error':
                app.logger.error('Error charging order: %s', root['error-message'])
                return ('', 500)

            elif root.tag != GCO.schema + 'request-received':
                app.logger.error('Unexpected response charging order: %s', root.tag)
                return ('', 500)

            # root will contain a charge-amount-notification, but we'll get called back, too

            p.state = 'charged'

        elif finance_state == 'CHARGED' and p.finance_state != 'CHARGED':
            p.state = 'paid'
            for ticket in p.tickets:
                ticket.paid = True

            msg = Message("Your EMF ticket payment has been confirmed",
                sender=app.config.get('TICKETS_EMAIL'),
                recipients=[p.user.email]
            )
            msg.body = render_template("tickets-paid-email-googlecheckout.txt",
                user = p.user, payment=p)
            mail.send(msg)

        p.finance_state = str(finance_state)
        p.fulfill_state = str(fulfill_state)
        db.session.commit()

    elif root.tag == GCO.schema + 'risk-information-notification':
        order_no = root['google-order-number']
        p = GoogleCheckoutPayment.query.filter_by(order_no=str(order_no)).one()

        risk = root['risk-information']
        ip = risk['ip-address']
        avs = risk['avs-response']
        cvn = risk['cvn-response']
        age = risk['buyer-account-age']
        # See https://developers.google.com/checkout/developer/Google_Checkout_XML_API_Notification_API for meanings
        app.logger.info('Risk info for payment %s: avs %s cvn %s ip %s age %s',
            p.id, avs, cvn, ip, age)

    elif root.tag == GCO.schema + 'charge-amount-notification':
        order_no = root['google-order-number']
        p = GoogleCheckoutPayment.query.filter_by(order_no=str(order_no)).one()

        amount = root['latest-charge-amount']
        pct = root['latest-charge-fee']['percentage']
        flat = root['latest-charge-fee']['flat']

        app.logger.error('Payment %s charged: %s %s (fee %s%% + %s %s)',
            p.id, amount, amount.get('currency'), pct, flat, flat.get('currency'))

        if p.state in ('new', 'reviewing'):
            # It was charged automatically or manually through the console (so don't ship it)
            p.state = 'charged'
            db.session.commit()


    return render_template('google-checkout/notification-acknowledgment.xml', serial=serial)


