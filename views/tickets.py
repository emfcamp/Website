from main import app, db
from views import (
    get_user_currency, get_basket, TICKET_CUTOFF,
    IntegerSelectField, HiddenIntegerField,
)
from views.payment.banktransfer import BankTransferCancelForm
from views.payment.gocardless import GoCardlessTryAgainForm

from models.user import User
from models.ticket import TicketType, Ticket, TicketAttrib, TicketToken
from models.payment import Payment

from flask import (
    render_template, redirect, request, flash,
    url_for, session, send_file,
)
from flask.ext.login import login_required, current_user

from sqlalchemy.orm.exc import NoResultFound

from flask_wtf import Form
from wtforms.validators import Required, Optional
from wtforms import (
    SubmitField, BooleanField,
    DecimalField, FieldList, FormField,
)
from datetime import datetime, timedelta
from StringIO import StringIO
import qrcode

class TicketForm(Form):
    ticket_id = HiddenIntegerField('Ticket Type', [Required()])

class FullTicketForm(TicketForm):
    template = 'tickets/full.html'
    volunteer = BooleanField('Volunteering')
    accessible = BooleanField('Accessibility')

class KidsTicketForm(TicketForm):
    template = 'tickets/kids.html'
    accessible = BooleanField('Accessibility')

class CarparkTicketForm(TicketForm):
    template = 'tickets/carpark.html'
    carshare = BooleanField('Car share')

class CampervanTicketForm(TicketForm):
    pass
    # XXX do we need a template for these?
    # maybe info on where to go?
#    template= 'tickets/campervan.html'

class DonationTicketForm(TicketForm):
    template = 'tickets/donation.html'
    amount = DecimalField('Donation amount')

ticket_forms = ['full', 'kids']

def get_form_name(ticket_type):
    code, _, subcode = ticket_type.code.partition('_')
    if code not in ticket_forms:
        return None
    return code

class UpdateTicketForm(Form):
    pass

class UpdateTicketsForm(Form):
    tickets = FieldList(FormField(UpdateTicketForm))


@app.route("/tickets", methods=['GET', 'POST'])
def tickets():
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
        elif p.provider == "banktransfer" and p.state == "inprogress":
            retrycancel_forms[p.id] = BankTransferCancelForm(formdata=None, payment=p.id, yesno='no')
        # the rest are inprogress or complete gocardless payments
        # or complete banktransfers,
        # or canceled payments of either provider.

    return render_template("tickets.html",
        tickets=tickets,
        payments=payments,
        retrycancel_forms=retrycancel_forms,
    )


@app.route("/tickets/token/<token>")
def tickets_token(token):
    if TicketToken.types(token):
        session['ticket_token'] = token
    else:
        flash('Ticket token was invalid')

    return redirect(url_for('tickets_choose'))


class TicketAmountForm(Form):
    amount = IntegerSelectField('Number of tickets', [Optional()])
    code = HiddenIntegerField('Ticket Type', [Required()])

class TicketAmountsForm(Form):
    types = FieldList(FormField(TicketAmountForm))
    choose = SubmitField('Buy Tickets')

@app.route("/tickets/choose", methods=['GET', 'POST'])
def tickets_choose():
    if TICKET_CUTOFF:
        return render_template("tickets-cutoff.html")
    form = TicketAmountsForm(request.form)

    if not form.types:
        for tt in TicketType.query.order_by(TicketType.order).all():
            form.types.append_entry()
            form.types[-1].code.data = tt.code

    if current_user.is_authenticated():
        fulls = current_user.tickets.join(TicketType). \
            filter(TicketType.code.like('full%')). \
            count()
    else:
        fulls = 0

    token_tts = TicketToken.types(session.get('ticket_token'))
    token_only = ['full_ucl', 'full_hs', 'full_make', 'full_adafruit',
                    'full_hackaday', 'full_boingboing', 'full_dp']

    for f in form.types:
        tt = TicketType.query.get(f.code.data)
        f._type = tt

        limit = tt.user_limit(current_user)

        values = range(limit + 1)
        if tt.code in token_only and tt not in token_tts:
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
                basket += [tt.code] * f.amount.data

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


@app.route("/tickets/receipt")
@login_required
def tickets_all_receipts():

    if current_user.receipt is None:
        current_user.create_receipt()

    tickets = current_user.tickets.filter_by(paid=True).all()
    for ticket in tickets:
        if ticket.receipt is None:
            ticket.create_receipt()

    return render_template('tickets-receipt.htm', user=current_user, tickets=tickets)

@app.route("/receipt/<receipt>")
@login_required
def tickets_receipt(receipt):
    if current_user.admin:
        return redirect(url_for('admin_receipt', receipt=receipt))

    try:
        user = User.filter_by(receipt=receipt).one()
        tickets = list(user.tickets)
    except NoResultFound, e:
        try:
            ticket = Ticket.filter_by(receipt=receipt).one()
            tickets = [ticket]
            user = ticket.user
        except NoResultFound, e:
            return ('', 404)

    if current_user != user:
        return ('', 404)

    return render_template('tickets-receipt.htm', user=user, tickets=tickets)

@app.route("/receipt/<receipt>/qr")
@login_required
def tickets_receipt_qr(receipt):

    qrfile = StringIO()
    qr = qrcode.make(url_for('tickets_receipt', receipt=receipt, _external=True), box_size=2)
    qr.save(qrfile, 'PNG')
    qrfile.seek(0)
    return send_file(qrfile, mimetype='image/png')


