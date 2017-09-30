from datetime import datetime, timedelta
from decimal import Decimal
import re

from flask import (
    render_template, redirect, request, flash, Blueprint,
    url_for, session, send_file, abort, current_app as app,
    Markup, render_template_string,
)
from flask.ext.login import login_required, current_user
from flask_mail import Message
from wtforms.validators import Required, Optional, Email, ValidationError
from wtforms import (
    SubmitField, StringField,
    FieldList, FormField, HiddenField,
)
from wtforms.fields.html5 import EmailField
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound

from main import db, mail
from models.user import User, checkin_code_re
from models.product import ProductGroup
from models import bought_states
# from models.ticket import TicketLimitException, TicketType
from models.payment import BankPayment, StripePayment, GoCardlessPayment
from models.site_state import get_sales_state
from models.payment import Payment


from .common import (
    get_user_currency, set_user_currency, get_basket_and_total, create_basket,
    CURRENCY_SYMBOLS, feature_flag, create_current_user, feature_enabled,
)
from .common.forms import IntegerSelectField, HiddenIntegerField, Form
from .common.receipt import (
    make_qr_png, make_barcode_png, render_pdf, render_receipt, attach_tickets,
)
from .payments.gocardless import gocardless_start
from .payments.banktransfer import transfer_start
from .payments.stripe import stripe_start


tickets = Blueprint('tickets', __name__)


def create_payment(paymenttype):
    """
    Insert payment and tickets from session data into DB
    """

    infodata = session.get('ticketinfo')
    basket, total = create_basket()  # creates Ticket objects
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
        # current_user.tickets.append(ticket) # this shouldn't be needed
        ticket.payment = payment
        if currency == 'GBP':
            ticket.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS_TRANSFER'))
        elif currency == 'EUR':
            ticket.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS_TRANSFER_EURO'))

    db.session.commit()

    session.pop('basket', None)
    session.pop('ticketinfo', None)

    return payment


@tickets.route("/tickets/", methods=['GET', 'POST'])
def main():
    if current_user.is_anonymous:
        return redirect(url_for('tickets.choose'))

    all_tickets = current_user.products \
                              .join(ProductGroup) \
                              .outerjoin(Payment) \
                              .filter(or_(Payment.id.is_(None),
                                          Payment.state != "cancelled"
                                        )
                                      )

    tickets = all_tickets.filter_by(is_ticket=True).all()
    other_items = all_tickets.filter(is_ticket=False).all()
    payments = current_user.payments.filter(Payment.state != "cancelled").all()

    if not tickets and not payments:
        return redirect(url_for('tickets.choose'))

    transferred_to = current_user.transfers_to.all()
    transferred_from = current_user.transfers_from.all()

    show_receipt = any([tt for tt in tickets if tt.paid is True])

    return render_template("tickets-main/main.html",
                           tickets=tickets,
                           other_items=other_items,
                           payments=payments,
                           show_receipt=show_receipt,
                           transferred_to=transferred_to,
                           transferred_from=transferred_from)


@tickets.route("/tickets/token/")
@tickets.route("/tickets/token/<token>")
def tickets_token(token=None):
    tts = ProductGroup.get_product_groups_for_token(token)
    if tts:
        session['ticket_token'] = token
    else:
        if 'ticket_token' in session:
            del session['ticket_token']
        flash('Ticket token was invalid')

    if any(tt.allow_check_in for tt in tts):
        return redirect(url_for('tickets.choose'))

    return redirect(url_for('tickets.choose', flow='other'))


class TicketAmountForm(Form):
    amount = IntegerSelectField('Number of tickets', [Optional()])
    type_id = HiddenIntegerField('Ticket Type', [Required()])


class TicketAmountsForm(Form):
    types = FieldList(FormField(TicketAmountForm))
    buy = SubmitField('Buy Tickets')
    buy_other = SubmitField('Buy')
    currency_code = HiddenField('Currency')
    set_currency = StringField('Set Currency', [Optional()])

    def validate_set_currency(form, field):
        if field.data not in CURRENCY_SYMBOLS:
            raise ValidationError('Invalid currency %s' % field.data)


@tickets.route("/tickets/choose", methods=['GET', 'POST'])
@tickets.route("/tickets/choose/<flow>", methods=['GET', 'POST'])
@feature_flag('TICKET_SALES')
def choose(flow=None):
    token = session.get('ticket_token')
    sales_state = get_sales_state()

    if flow is None:
        admissions = True
    elif flow == 'other':
        admissions = False
    else:
        abort(404)

    if sales_state in ['unavailable', 'sold-out']:
        # For the main entry point, we assume people want admissions tickets,
        # but we still need to sell people e.g. parking tickets or tents until
        # the final cutoff (sales-ended).
        if not admissions:
            sales_state = 'available'

        # Allow people with valid discount tokens to buy tickets
        elif token is not None and ProductGroup.get_product_groups_for_token(token):
            sales_state = 'available'


    if app.config.get('DEBUG'):
        sales_state = request.args.get("sales_state", sales_state)

    if sales_state == 'available':
        pass
    elif not current_user.is_anonymous and current_user.has_permission('admin'):
        pass
    else:
        return render_template("tickets-cutoff.html")

    form = TicketAmountsForm()

    # If this is the main page, exclude tents and other paraphernalia.
    # For the non-admissions page, only exclude actual admissions tickets.
    # This means both pages show parking and caravan tickets.
    if admissions:
        tts = ProductGroup.query.filter_by(allow_check_in=True, is_visible=True)
    else:
        tts = ProductGroup.query.filter_by(allow_check_in=False, is_visible=True)

    tts = tts.order_by(ProductGroup.order).all()
    limits = dict((tt.id, tt.user_limit(current_user, token)) for tt in tts)

    if request.method != 'POST':
        # Empty form - populate ticket types
        for tt in tts:
            form.types.append_entry()
            form.types[-1].type_id.data = tt.id


    tts = {tt.id: tt for tt in tts}
    for f in form.types:
        t_id = f.type_id.data
        f._type = tts[t_id]

        values = range(limits[t_id] + 1)
        f.amount.values = values
        f._any = any(values)

    if form.validate_on_submit():
        if form.buy.data or form.buy_other.data:
            set_user_currency(form.currency_code.data)

            basket = []
            for f in form.types:
                if f.amount.data:
                    tt = f._type
                    app.logger.info('Adding %s %s tickets to basket', f.amount.data, tt.name)
                    basket += [tt.id] * f.amount.data
                    # FIXME Should be able to create actual ProductInstances here rather than
                    # attach them to the session
            if basket:
                session['basket'] = basket

                return redirect(url_for('tickets.pay', flow=flow))
            elif admissions:
                flash("Please select at least one ticket to buy.")
            else:
                flash("Please select at least one item to buy.")

    if request.method == 'POST' and form.set_currency.data:
        if form.set_currency.validate(form):
            app.logger.info("Updating currency to %s only", form.set_currency.data)
            set_user_currency(form.set_currency.data)

            for field in form:
                field.errors = []

    form.currency_code.data = get_user_currency()

    return render_template("tickets-choose.html", form=form, admissions=admissions)


class TicketPaymentForm(Form):
    email = EmailField('Email', [Email(), Required()])
    name = StringField('Name', [Required()])
    basket_total = HiddenField('basket total')

    gocardless = SubmitField('Pay by Direct Debit')
    banktransfer = SubmitField('Pay by Bank Transfer')
    stripe = SubmitField('Pay by card')

    def validate_email(form, field):
        if current_user.is_anonymous and User.does_user_exist(field.data):
            field.was_duplicate = True
            pay_url = url_for('tickets.pay', flow=form.flow)

            msg = Markup(render_template_string('''Account already exists.
                Please <a href="{{ url }}">click here</a> to log in.''',
                url=url_for('users.login', next=pay_url, email=field.data)))

            raise ValidationError(msg)


@tickets.route("/tickets/pay", methods=['GET', 'POST'])
@tickets.route("/tickets/pay/<flow>", methods=['GET', 'POST'])
def pay(flow=None):

    if flow is None:
        admissions = True
    elif flow == 'other':
        admissions = False
    else:
        abort(404)

    if request.form.get("change_currency") in ('GBP', 'EUR'):
        set_user_currency(request.form.get("change_currency"))
        return redirect(url_for('.pay'))

    form = TicketPaymentForm()
    form.flow = flow

    if not current_user.is_anonymous:
        del form.email
        del form.name

    basket, total = get_basket_and_total(get_user_currency())
    if not basket:
        if admissions:
            flash("Please select at least one ticket to buy.")
        else:
            flash("Please select at least one item to buy.")
        return redirect(url_for('tickets.main'))

    if form.validate_on_submit():
        if Decimal(form.basket_total.data) != Decimal(total):
            # Check that the user's basket approximately matches what we told them they were paying.
            app.logger.warn("User's basket has changed value %s -> %s", form.basket_total.data, total)
            flash("""The tickets you selected have changed, possibly because you had two windows open.
                  Please verify that you've selected the correct tickets.""")
            return redirect(url_for('tickets.pay', flow=flow))

        if current_user.is_anonymous:
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

        #
        try:
            payment = create_payment(payment_type)
        # FIXME this should be a much more tightly scoped exception
        except Exception as e: # TicketLimitException as e:
            app.logger.warn('Limit exceeded creating tickets: %s', e)
            flash("We're sorry, we were unable to reserve your tickets. %s" % e)
            return redirect(url_for('tickets.choose', flow=flow))

        if not payment:
            app.logger.warn('Unable to add payment and tickets to database')
            flash("We're sorry, your session information has been lost. Please try ordering again.")
            return redirect(url_for('tickets.choose', flow=flow))

        if payment_type == GoCardlessPayment:
            return gocardless_start(payment)
        elif payment_type == BankPayment:
            return transfer_start(payment)
        elif payment_type == StripePayment:
            return stripe_start(payment)

    form.basket_total.data = total

    return render_template('payment-choose.html', form=form,
                           basket=basket, total=total, StripePayment=StripePayment,
                           is_anonymous=current_user.is_anonymous,
                           admissions=admissions)


class TicketTransferForm(Form):
    name = StringField('Name', [Required()])
    email = EmailField('Email', [Required()])

    transfer = SubmitField('Transfer Ticket')

    def validate_email(form, field):
        if current_user.email == field.data:
            raise ValidationError('You cannot transfer a ticket to yourself')

@tickets.route('/tickets/<ticket_id>/transfer', methods=['GET', 'POST'])
@login_required
def transfer(ticket_id):
    try:
        ticket = current_user.tickets.filter_by(id=ticket_id).one()
    except NoResultFound:
        return redirect(url_for('tickets.main'))

    if not ticket or ticket.state not in bought_states or not ticket.type.is_transferable:
        return redirect(url_for('tickets.main'))

    form = TicketTransferForm()

    if form.validate_on_submit():
        assert ticket.user_id == current_user.id
        email = form.email.data

        if not User.does_user_exist(email):
            new_user = True

            # Create a new user to transfer the ticket to
            to_user = User(email, form.name.data)
            db.session.add(to_user)
            db.session.commit()

        else:
            new_user = False
            to_user = User.query.filter_by(email=email).one()

        ticket.transfer(from_user=current_user, to_user=to_user)

        app.logger.info('Ticket %s transferred from %s to %s', ticket,
                        current_user, to_user)

        # Alert the users via email
        code = to_user.login_code(app.config['SECRET_KEY'])

        msg = Message("You've been sent a ticket to EMF 2016!",
                      sender=app.config.get('TICKETS_EMAIL'),
                      recipients=[to_user.email])
        msg.body = render_template('emails/ticket-transfer-new-owner.txt',
                            to_user=to_user, from_user=current_user,
                            new_user=new_user, code=code)

        if feature_enabled('ISSUE_TICKETS'):
            attach_tickets(msg, to_user)

        mail.send(msg)
        db.session.commit()

        msg = Message("You sent someone an EMF 2016 ticket",
                      sender=app.config.get('TICKETS_EMAIL'),
                      recipients=[current_user.email])
        msg.body = render_template('emails/ticket-transfer-original-owner.txt',
                            to_user=to_user, from_user=current_user)

        mail.send(msg)

        flash("Your ticket was transferred.")
        return redirect(url_for('tickets.main'))

    return render_template('ticket-transfer.html', ticket=ticket, form=form)


@tickets.route("/tickets/receipt")
@tickets.route("/tickets/<int:user_id>/receipt")
@login_required
def receipt(user_id=None):
    if current_user.has_permission('admin') and user_id is not None:
        user = User.query.get(user_id)
    else:
        user = current_user

    if not user.tickets.filter_by(state='paid').all():
        abort(404)

    png = bool(request.args.get('png'))
    pdf = bool(request.args.get('pdf'))

    page = render_receipt(user, png, pdf)
    if pdf:
        return send_file(render_pdf(page), mimetype='application/pdf')

    return page


# Generate a PNG-based QR code as xhtml2pdf doesn't support SVG.
#
# This only accepts the code on purpose - we can't authenticate the
# user from the PDF renderer, and a full URL is awkward to validate.
@tickets.route("/receipt/<checkin_code>/qr")
def tickets_qrcode(checkin_code):
    if not re.match('%s$' % checkin_code_re, checkin_code):
        abort(404)

    url = app.config.get('CHECKIN_BASE') + checkin_code

    qrfile = make_qr_png(url, box_size=3)
    return send_file(qrfile, mimetype='image/png')

@tickets.route("/receipt/<checkin_code>/barcode")
def tickets_barcode(checkin_code):
    if not re.match('%s$' % checkin_code_re, checkin_code):
        abort(404)

    barcodefile = make_barcode_png(checkin_code)
    return send_file(barcodefile, mimetype='image/png')

