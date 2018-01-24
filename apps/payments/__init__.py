from decimal import Decimal
from flask import render_template, redirect, url_for, abort, flash, current_app as app, Blueprint
from flask_login import login_required, current_user
from sqlalchemy.sql.functions import func

from models.payment import Payment
from models.product import Product, PriceTier
from models.purchase import Purchase

payments = Blueprint('payments', __name__)


def get_user_payment_or_abort(payment_id, provider=None, valid_states=None, allow_admin=False):
    try:
        payment = Payment.query.get(payment_id)
    except Exception as e:
        app.logger.warning('Exception %r getting payment %s', e, payment_id)
        abort(404)

    if not payment:
        app.logger.warning('Payment %s does not exist.', payment_id)
        abort(404)

    if not (payment.user == current_user or (allow_admin and current_user.has_permission('admin'))):
        app.logger.warning('User not allowed to access payment %s', payment_id)
        abort(404)

    if provider and payment.provider != provider:
        app.logger.warning('Payment %s is of type %s, not %s', payment.provider, provider)
        abort(404)

    if valid_states and payment.state not in valid_states:
        app.logger.warning("Payment %s is %s, not one of %s", payment_id, payment.state, valid_states)
        abort(404)

    return payment


@payments.route("/pay/terms")
def terms():
    return render_template('terms.html')


@payments.route('/payment/<int:payment_id>/invoice')
@login_required
def invoice(payment_id):
    payment = get_user_payment_or_abort(payment_id, allow_admin=True)

    invoice_lines = Purchase.query.filter_by(payment_id=payment_id).join(PriceTier, Product) \
        .with_entities(PriceTier, func.count(Purchase.price_tier_id)) \
        .group_by(PriceTier, Product.name).order_by(Product.name).all()

    ticket_sum = sum(pt.get_price(payment.currency).value_ex_vat * count for pt, count in invoice_lines)
    if payment.provider == 'stripe':
        premium = payment.__class__.premium(payment.currency, ticket_sum)
    else:
        premium = Decimal(0)

    subtotal = ticket_sum + premium
    vat = subtotal * Decimal('0.2')
    app.logger.debug('Invoice subtotal %s + %s = %s', ticket_sum, premium, subtotal)

    # FIXME: we should use a currency-specific quantization here (or rounder numbers)
    if subtotal + vat - payment.amount > Decimal('0.01'):
        app.logger.error('Invoice total mismatch: %s + %s - %s = %s', subtotal, vat,
                         payment.amount, subtotal + vat - payment.amount)
        flash('Your invoice cannot currently be displayed')
        return redirect(url_for('tickets.main'))

    app.logger.debug('Invoice total: %s + %s = %s', subtotal, vat, payment.amount)

    return render_template('invoice.html', payment=payment, invoice_lines=invoice_lines,
                           premium=premium, subtotal=subtotal, vat=vat)


from . import banktransfer  # noqa: F401
from . import gocardless  # noqa: F401
from . import stripe  # noqa: F401

