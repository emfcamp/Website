from datetime import datetime
from decimal import Decimal
import re
from collections import OrderedDict

from flask import (
    render_template, redirect, request, flash, Blueprint,
    url_for, session, send_file, abort, current_app as app,
)
from flask_login import login_required, current_user
from flask_mail import Message
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from main import db, mail
from models.exc import CapacityException
from models.user import User, checkin_code_re
from models.product import (
    PriceTier, ProductView,
    ProductViewProduct, Product,
)
from models import bought_states
from models.basket import Basket
from models.payment import BankPayment, StripePayment, GoCardlessPayment
from models.purchase import Ticket
from models.site_state import get_sales_state, config_date

from ..common import (
    get_user_currency, set_user_currency,
    feature_flag, create_current_user, feature_enabled,
)
from ..common.receipt import (
    make_qr_png, make_barcode_png, render_pdf, render_receipt, attach_tickets,
)
from ..payments.gocardless import gocardless_start
from ..payments.banktransfer import transfer_start
from ..payments.stripe import stripe_start

from .forms import TicketAmountsForm, TicketTransferForm, TicketPaymentForm

tickets = Blueprint('tickets', __name__)


@tickets.route("/tickets/token/")
@tickets.route("/tickets/token/<token>")
def tickets_token(token=None):
    view = ProductView.get_by_token(token)
    if view:
        session['ticket_token'] = token
        return redirect(url_for('tickets.main', flow=view.name))

    if 'ticket_token' in session:
        del session['ticket_token']
    flash('Ticket token was invalid')
    return redirect(url_for('tickets.main'))



@tickets.route("/tickets", methods=['GET', 'POST'])
@tickets.route("/tickets/<flow>", methods=['GET', 'POST'])
@feature_flag('TICKET_SALES')
def main(flow=None):
    if flow is None:
        flow = 'main'

    # For now, use the flow name as a view name. This might change.
    view = ProductView.get_by_name(flow)
    if not view:
        abort(404)

    if datetime.utcnow() < config_date('SALES_START') and not view.token:
        # Allow us to set TICKET_SALES before sales start
        abort(404)

    if view.token and session.get('ticket_token') != view.token:
        # Users with the right tokens and admins can access token-based views
        if current_user.is_anonymous:
            abort(404)

        elif not current_user.has_permission('admin'):
            abort(404)

    is_new_basket = request.args.get('is_new_basket', False)
    if is_new_basket:
        basket = Basket.from_session(current_user, get_user_currency())
        basket.cancel_purchases()
        db.session.commit()

        Basket.clear_from_session()
        return redirect(url_for('tickets.main', flow=flow))

    sales_state = get_sales_state()

    if sales_state in ['unavailable', 'sold-out']:
        # For the main entry point, we assume people want admissions tickets,
        # but we still need to sell people parking tickets, tents or tickets
        # from tokens until the final cutoff (sales-ended).
        if flow != 'main':
            sales_state = 'available'

    if app.config.get('DEBUG'):
        sales_state = request.args.get("sales_state", sales_state)

    if sales_state == 'available':
        pass
    elif not current_user.is_anonymous and current_user.has_permission('admin'):
        pass
    else:
        return render_template("tickets-cutoff.html")

    tiers = OrderedDict()
    products = ProductViewProduct.query.filter_by(view_id=view.id) \
                                 .join(ProductViewProduct.product) \
                                 .with_entities(Product) \
                                 .order_by(ProductViewProduct.order) \
                                 .options(joinedload(Product.price_tiers)
                                          .joinedload(PriceTier.prices)
                                 )

    ticket_view = False
    for product in products:
        pts = [tier for tier in product.price_tiers if tier.active]
        if len(pts) > 1:
            app.logger.error("Multiple active PriceTiers found for %s. Excluding product.", product)
            continue

        pt = pts[0]

        tiers[pt.id] = pt
        if product.parent.type == 'admissions':
            ticket_view = True

    basket = Basket.from_session(current_user, get_user_currency())

    form = TicketAmountsForm()

    """
    For consistency and to avoid surprises, we try to ensure a few things here:
    - if the user successfully submits a form with no errors, their basket is updated
    - if they don't, the basket is left untouched
    - the basket is updated to match what was submitted, even if they added tickets in another tab
    - if they already have tickets in their basket, only reserve the extra tickets as necessary
    - don't unreserve surplus tickets until the payment is created
    - if the user hasn't submitted anything, we use their current reserved ticket counts
    - if the user has reserved tickets from exhausted tiers on this view, we still show them
    - if the user has reserved tickets from other views, don't show and don't mess with them

    We currently don't deal with multiple price tiers being available around the same time.
    Reserved tickets from a previous tier should be cancelled before activating a new one.
    """
    if request.method != 'POST':
        # Empty form - populate products
        for pt_id, tier in tiers.items():
            form.tiers.append_entry()
            f = form.tiers[-1]
            f.tier_id.data = pt_id

            f.amount.data = basket.get(tier, 0)


    # Whether submitted or not, update the allowed amounts before validating
    capacity_gone = False
    for f in form.tiers:
        pt_id = f.tier_id.data
        tier = tiers[pt_id]
        f._tier = tier

        # If they've already got reserved tickets, let them keep them
        user_limit = max(tier.user_limit(), basket.get(tier, 0))
        if f.amount.data > user_limit:
            capacity_gone = True
        values = range(user_limit + 1)
        f.amount.values = values
        f._any = any(values)

    if form.validate_on_submit():
        if form.buy.data or form.buy_other.data:
            if form.currency_code.data != get_user_currency():
                set_user_currency(form.currency_code.data)
                # Commit so we don't lose the currency change if an error occurs
                db.session.commit()

            for f in form.tiers:
                if f.amount.data:
                    pt = f._tier
                    app.logger.info('Adding %s %s tickets to basket', f.amount.data, pt.name)
                    tier = PriceTier.query.get(pt.id)
                    basket[tier] = f.amount.data

            if any(basket.values()):
                app.logger.info('Basket %s', basket)

                try:
                    basket.create_purchases()
                    basket.ensure_purchase_capacity()

                    db.session.commit()

                except CapacityException as e:
                    # Damn, capacity's gone since we created the purchases
                    # Redirect back to show what's currently in the basket
                    app.logger.warn('Limit exceeded creating tickets: %s', e)
                    flash("We're very sorry, but there is not enough capacity available to "
                          "allocate these tickets. You may be able to try again with a smaller amount.")
                    return redirect(url_for("tickets.main", flow=flow))

                basket.save_to_session()

                return redirect(url_for('tickets.pay', flow=flow))

            elif ticket_view:
                flash("Please select at least one ticket to buy.")
            else:
                flash("Please select at least one item to buy.")

    if request.method == 'POST' and form.set_currency.data:
        if form.set_currency.validate(form):
            app.logger.info("Updating currency to %s only", form.set_currency.data)
            set_user_currency(form.set_currency.data)
            db.session.commit()

            for field in form:
                field.errors = []

    if capacity_gone:
        flash("We're sorry, but there is not enough capacity available to "
              "allocate these tickets. You may be able to try again with a smaller amount.")

    form.currency_code.data = get_user_currency()
    return render_template("tickets-choose.html", form=form, flow=flow, ticket_view=ticket_view)


@tickets.route("/tickets/pay", methods=['GET', 'POST'])
@tickets.route("/tickets/pay/<flow>", methods=['GET', 'POST'])
def pay(flow=None):
    view = ProductView.get_by_name(flow)
    if not view:
        abort(404)

    if view.token and session.get('ticket_token') != view.token:
        if not current_user.is_anonymous and current_user.has_permission('admin'):
            abort(404)

    if request.form.get("change_currency") in ('GBP', 'EUR'):
        set_user_currency(request.form.get("change_currency"))
        db.session.commit()

        return redirect(url_for('.pay', flow=flow))

    form = TicketPaymentForm()
    form.flow = flow

    if not current_user.is_anonymous:
        del form.email
        del form.name

    basket = Basket.from_session(current_user, get_user_currency())
    if not any(basket.values()):
        if flow == 'main':
            flash("Please select at least one ticket to buy.")
        else:
            flash("Please select at least one item to buy.")
        return redirect(url_for('tickets.main'))

    if form.validate_on_submit():
        if Decimal(form.basket_total.data) != Decimal(basket.total):
            # Check that the user's basket approximately matches what we told them they were paying.
            app.logger.warn("User's basket has changed value %s -> %s", form.basket_total.data, basket.total)
            flash("""The tickets you selected have changed, possibly because you had two windows open.
                  Please verify that you've selected the correct tickets.""")
            return redirect(url_for('tickets.pay', flow=flow))

        user = current_user
        if user.is_anonymous:
            try:
                new_user = create_current_user(form.email.data, form.name.data)
            except IntegrityError as e:
                app.logger.warn('Adding user raised %r, possible double-click', e)
                return None

            user = new_user

        if form.allow_promo.data:
            user.promo_opt_in = True

        if form.gocardless.data:
            payment_type = GoCardlessPayment
        elif form.banktransfer.data:
            payment_type = BankPayment
        elif form.stripe.data:
            payment_type = StripePayment

        basket.user = user
        payment = basket.create_payment(payment_type)
        basket.cancel_surplus_purchases()
        db.session.commit()

        Basket.clear_from_session()

        if not payment:
            app.logger.warn('User tried to pay for empty basket')
            flash("We're sorry, your session information has been lost. Please try ordering again.")
            return redirect(url_for('tickets.main', flow=flow))

        if payment_type == GoCardlessPayment:
            return gocardless_start(payment)
        elif payment_type == BankPayment:
            return transfer_start(payment)
        elif payment_type == StripePayment:
            return stripe_start(payment)

    form.basket_total.data = basket.total

    return render_template('payment-choose.html', form=form,
                           basket=basket, total=basket.total,
                           is_anonymous=current_user.is_anonymous,
                           flow=flow)


@tickets.route('/tickets/<ticket_id>/transfer', methods=['GET', 'POST'])
@login_required
def transfer(ticket_id):
    try:
        ticket = current_user.tickets.filter_by(id=ticket_id).one()
    except NoResultFound:
        return redirect(url_for('users.tickets'))

    if (not ticket or
            ticket.state not in bought_states or
            not ticket.price_tier.get_attribute('is_transferable')):
        return redirect(url_for('users.tickets'))

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

        Ticket.query.with_for_update.get(ticket_id)
        ticket.transfer(from_user=current_user, to_user=to_user)
        db.session.commit()

        app.logger.info('Ticket %s transferred from %s to %s', ticket,
                        current_user, to_user)

        # Alert the users via email
        code = to_user.login_code(app.config['SECRET_KEY'])

        msg = Message("You've been sent a ticket to EMF!",
                      sender=app.config.get('TICKETS_EMAIL'),
                      recipients=[to_user.email])
        msg.body = render_template('emails/ticket-transfer-new-owner.txt',
                                   to_user=to_user, from_user=current_user,
                                   new_user=new_user, code=code)

        if feature_enabled('ISSUE_TICKETS'):
            attach_tickets(msg, to_user)

        mail.send(msg)
        db.session.commit()

        msg = Message("You sent someone an EMF ticket",
                      sender=app.config.get('TICKETS_EMAIL'),
                      recipients=[current_user.email])
        msg.body = render_template('emails/ticket-transfer-original-owner.txt',
                                   to_user=to_user, from_user=current_user)

        mail.send(msg)

        flash("Your ticket was transferred.")
        return redirect(url_for('users.tickets'))

    return render_template('ticket-transfer.html', ticket=ticket, form=form)


@tickets.route("/tickets/receipt")
@tickets.route("/tickets/<int:user_id>/receipt")
@login_required
def receipt(user_id=None):
    if current_user.has_permission('admin') and user_id is not None:
        user = User.query.get(user_id)
    else:
        user = current_user

    if not user.owned_tickets.filter_by(state='paid').all():
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
