from datetime import datetime, timedelta
from flask import (
    render_template, redirect, request, flash, Blueprint,
    url_for, session, send_file, abort, current_app as app
)
from flask.ext.login import login_required, current_user
from wtforms.validators import Required, Optional, Email, ValidationError
from wtforms import (
    SubmitField, StringField,
    FieldList, FormField, HiddenField,
)
from wtforms.fields.html5 import EmailField
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound

from main import db
from .common import (
    get_user_currency, set_user_currency, get_basket_and_total, process_basket,
    CURRENCY_SYMBOLS, feature_flag, create_current_user, send_template_email)
from .common.forms import IntegerSelectField, HiddenIntegerField, Form
from .common.receipt import make_qr_png, render_pdf, render_receipt
from models.user import User
from models.ticket import TicketType, Ticket, validate_safechars
from models.payment import BankPayment, StripePayment, GoCardlessPayment
from models.site_state import get_sales_state
from models.payment import Payment
from payments.gocardless import gocardless_start
from payments.banktransfer import transfer_start
from payments.stripe import stripe_start


tickets = Blueprint('tickets', __name__)


class TicketForm(Form):
    ticket_id = HiddenIntegerField('Ticket Type', [Required()])


def create_payment(paymenttype):
    """
    Insert payment and tickets from session data into DB
    """

    infodata = session.get('ticketinfo')
    basket, total = process_basket()
    currency = get_user_currency()

    if not (basket and total):
        return None

    payment = paymenttype(currency, total)
    payment.amount += paymenttype.premium(currency, total)
    current_user.payments.append(payment)

    app.logger.info('Creating tickets for basket %s', basket)
    app.logger.info('Payment: %s for %s %s (ticket total %s)', paymenttype.name,
                    payment.amount, currency, total)
    app.logger.info('Ticket info: %s', infodata)

    for ticket in basket:
        current_user.tickets.append(ticket)
        ticket.payment = payment
        if currency == 'GBP':
            ticket.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS_TRANSFER'))
        elif currency == 'EUR':
            ticket.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS_TRANSFER_EURO'))

    db.session.commit()

    session.pop('basket', None)
    session.pop('ticketinfo', None)

    return payment


class ReceiptForm(Form):
    forward = SubmitField('Show e-Tickets')


@tickets.route("/tickets/", methods=['GET', 'POST'])
def main():
    if current_user.is_anonymous():
        return redirect(url_for('tickets.choose'))

    form = ReceiptForm()
    if form.validate_on_submit():
        ticket_ids = map(str, request.form.getlist('ticket_id', type=int))
        if ticket_ids:
            return redirect(url_for('tickets.receipt', ticket_ids=','.join(ticket_ids)) + '?pdf=1')
        return redirect(url_for('tickets.receipt') + '?pdf=1')

    tickets = current_user.tickets.join(Payment).filter(Payment.state != "cancelled",
                                                        Payment.state != "expired").all()

    payments = current_user.payments.filter(Payment.state != "cancelled", Payment.state != "expired").all()

    if not tickets and not payments:
        return redirect(url_for('tickets.choose'))

    transferred_to = current_user.transfers_to.all()
    transferred_from = current_user.transfers_from.all()

    show_receipt = any([tt for tt in tickets if tt.paid is True])

    return render_template("tickets-main/main.html",
                           tickets=tickets,
                           payments=payments,
                           form=form,
                           show_receipt=show_receipt,
                           transferred_to=transferred_to,
                           transferred_from=transferred_from)


@tickets.route("/tickets/token/")
@tickets.route("/tickets/token/<token>")
def tickets_token(token=None):
    if TicketType.get_types_for_token(token):
        session['ticket_token'] = token
    else:
        if 'ticket_token' in session:
            del session['ticket_token']
        flash('Ticket token was invalid')

    return redirect(url_for('tickets.choose'))


class TicketAmountForm(Form):
    amount = IntegerSelectField('Number of tickets', [Optional()])
    code = HiddenIntegerField('Ticket Type', [Required()])


class TicketAmountsForm(Form):
    types = FieldList(FormField(TicketAmountForm))
    buy = SubmitField('Buy Tickets')
    currency_code = HiddenField('Currency')
    set_currency = StringField('Set Currency', [Optional()])

    def validate_set_currency(form, field):
        if field.data not in CURRENCY_SYMBOLS:
            raise ValidationError('Invalid currency %s' % field.data)


@tickets.route("/tickets/choose", methods=['GET', 'POST'])
@feature_flag('TICKET_SALES')
def choose():
    if get_sales_state(datetime.utcnow()) != 'available':
        return render_template("tickets-cutoff.html")

    form = TicketAmountsForm()

    tts = TicketType.query.order_by(TicketType.order).all()

    token = session.get('ticket_token')
    limits = dict([(tt.id, tt.user_limit(current_user, token)) for tt in tts])

    if request.method != 'POST':
        # Empty form - populate ticket types
        first_full = False
        for tt in tts:
            form.types.append_entry()
            # Set as unicode because that's what the browser will return
            form.types[-1].code.data = tt.id

            if (not first_full) and (tt.admits == 'full') and (limits[tt.id] > 0):
                first_full = True
                form.types[-1].amount.data = 1

    tts = dict((tt.id, tt) for tt in tts)
    for f in form.types:
        t_id = int(f.code.data)  # On form return this may be a string
        f._type = tts[t_id]

        values = range(limits[t_id] + 1)
        f.amount.values = values
        f._any = any(values)

    if form.validate_on_submit():
        if form.buy.data:
            set_user_currency(form.currency_code.data)

            basket = []
            for f in form.types:
                if f.amount.data:
                    tt = f._type
                    app.logger.info('Adding %s %s tickets to basket', f.amount.data, tt.name)
                    basket += [tt.id] * f.amount.data

            if basket:
                session['basket'] = basket

                return redirect(url_for('tickets.pay'))
            else:
                flash("Please select at least one ticket to buy.")

    if request.method == 'POST' and form.set_currency.data:
        if form.set_currency.validate(form):
            app.logger.info("Updating currency to %s only", form.set_currency.data)
            set_user_currency(form.set_currency.data)

            for field in form:
                field.errors = []

    form.currency_code.data = get_user_currency()

    return render_template("tickets-choose.html", form=form)


class TicketPaymentForm(Form):
    email = EmailField('Email', [Email(), Required()])
    name = StringField('Name', [Required()])
    basket_total = HiddenField('basket total')

    gocardless = SubmitField('Pay by Direct Debit')
    banktransfer = SubmitField('Pay by Bank Transfer')
    stripe = SubmitField('Pay by card')

    def validate_email(form, field):
        if current_user.is_anonymous() and User.does_user_exist(field.data):
            field.was_duplicate = True
            raise ValidationError('Account already exists')


@tickets.route("/tickets/pay", methods=['GET', 'POST'])
def pay():
    form = TicketPaymentForm()

    if not current_user.is_anonymous():
        del form.email
        del form.name

    basket, total = get_basket_and_total()
    if not basket:
        flash("Please select at least one ticket to buy.")
        return redirect(url_for('tickets.main'))

    if form.validate_on_submit():
        if int(form.basket_total.data) != int(total):
            # Check that the user's basket approximately matches what we told them they were paying.
            app.logger.warn("User's basket has changed value %s -> %s", form.basket_total.data, total)
            flash("""The tickets you selected have changed, possibly because you had two windows open.
                  Please verify that you've selected the correct tickets.""")
            return redirect(url_for('tickets.pay'))

        if current_user.is_anonymous():
            try:
                create_current_user(form.email.data, form.name.data)
            except IntegrityError as e:
                app.logger.warn('Adding user raised %r, possible double-click', e)
                return None

        if form.gocardless.data:
            payment_type = GoCardlessPayment
        elif form.banktransfer.data:
            payment_type = BankPayment
        elif form.stripe.data:
            payment_type = StripePayment

        payment = create_payment(payment_type)
        if not payment:
            app.logger.warn('Unable to add payment and tickets to database')
            flash("We're sorry, your session information has been lost. Please try ordering again.")
            return redirect(url_for('tickets.choose'))

        if payment_type == GoCardlessPayment:
            return gocardless_start(payment)
        elif payment_type == BankPayment:
            return transfer_start(payment)
        elif payment_type == StripePayment:
            return stripe_start(payment)

    form.basket_total.data = total

    return render_template('payment-choose.html', form=form,
                           basket=basket, total=total, StripePayment=StripePayment,
                           is_anonymous=current_user.is_anonymous())


class TicketTransferForm(Form):
    email = EmailField('Email', [Required()])
    name = StringField('Name', [Required()])

    transfer = SubmitField('Transfer Ticket')


@tickets.route('/tickets/<ticket_id>/transfer', methods=['GET', 'POST'])
@login_required
def transfer(ticket_id):
    try:
        ticket = current_user.tickets.filter_by(id=ticket_id).one()
    except NoResultFound:
        return redirect(url_for('tickets.main'))

    if not ticket or not ticket.paid or not ticket.type.is_transferable:
        return redirect(url_for('tickets.main'))

    form = TicketTransferForm()

    if form.validate_on_submit():
        assert ticket.user_id == current_user.id
        email = form.email.data

        if not User.does_user_exist(email):
            # Create a new user to transfer the ticket to
            to_user = User(email, form.name.data)
            to_user.generate_random_password()
            db.session.add(to_user)
            db.session.commit()

            code = to_user.login_code(app.config['SECRET_KEY'])
            email_template = 'ticket-transfer-new-owner-and-user.txt'
        else:
            to_user = User.query.filter_by(email=email).one()
            code = None
            email_template = 'ticket-transfer-new-owner.txt'

        ticket.transfer(from_user=current_user, to_user=to_user)

        app.logger.info('Ticket %s transferred from %s to %s', ticket,
                        current_user, to_user)

        # Alert the users via email
        send_template_email("You've been sent a ticket to EMF 2016!",
                            to_user.email, current_user.email,
                            'emails/' + email_template,
                            to_user=to_user, from_user=current_user, code=code)

        send_template_email("You sent someone an EMF 2016 ticket",
                            to_user.email, current_user.email,
                            'emails/ticket-transfer-original-owner.txt',
                            to_user=to_user, from_user=current_user)

        return redirect(url_for('tickets.main'))

    return render_template('ticket-transfer.html', ticket=ticket, form=form)


@tickets.route("/tickets/receipt")
@tickets.route("/tickets/<ticket_ids>/receipt")
@login_required
def receipt(ticket_ids=None):
    if current_user.admin and ticket_ids is not None:
        tickets = Ticket.query
    else:
        tickets = current_user.tickets

    tickets = tickets.filter_by(paid=True) \
        .join(Payment).filter(~Payment.state.in_(['cancelled'])) \
        .join(TicketType).order_by(TicketType.order)

    if ticket_ids is not None:
        ticket_ids = map(int, ticket_ids.split(','))
        tickets = tickets.filter(Ticket.id.in_(ticket_ids))

    if not tickets.all():
        abort(404)

    png = bool(request.args.get('png'))
    pdf = bool(request.args.get('pdf'))
    table = bool(request.args.get('table'))

    page = render_receipt(tickets, png, table, pdf)
    if pdf:
        return send_file(render_pdf(page), mimetype='application/pdf')

    return page


@tickets.route("/receipt/<code>/qr")
def tickets_qrcode(code):
    if len(code) > 8:
        abort(404)

    if not validate_safechars(code):
        abort(404)

    url = app.config.get('CHECKIN_BASE') + code

    qrfile = make_qr_png(url, box_size=3)
    return send_file(qrfile, mimetype='image/png')
