from decimal import Decimal

from flask import (
    current_app as app, request,
    render_template, redirect, flash,
    url_for, send_file,
)
from flask_login import login_required, current_user
from sqlalchemy.sql.functions import func
from wtforms import TextAreaField, SubmitField

from main import external_url, db
from ..common.receipt import render_pdf
from models.product import Product, PriceTier
from models.purchase import Purchase
from ..common.forms import Form
from . import get_user_payment_or_abort
from . import payments

class InvoiceForm(Form):
    company = TextAreaField('Company name')
    update = SubmitField('Update')

@payments.route('/payment/<int:payment_id>/invoice', methods=['GET', 'POST'])
@login_required
def invoice(payment_id):
    payment = get_user_payment_or_abort(payment_id, allow_admin=True)

    form = InvoiceForm()

    if form.validate_on_submit():
        current_user.company = form.company.data
        db.session.commit()

        flash('Company name updated')
        return redirect(url_for('.invoice', payment_id=payment_id))

    if request.method != 'POST':
        form.company.data = current_user.company

    edit_company = bool(request.args.get('edit_company'))
    if request.args.get('js') == '0':
        flash("Please use your browser's print feature or download the PDF")

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
        return redirect(url_for('users.purchases'))

    app.logger.debug('Invoice total: %s + %s = %s', subtotal, vat, payment.amount)

    page = render_template('invoice.html', payment=payment, invoice_lines=invoice_lines, form=form,
                           premium=premium, subtotal=subtotal, vat=vat, edit_company=edit_company)

    if request.args.get('pdf'):
        url = external_url('.invoice', payment_id=payment_id)
        return send_file(render_pdf(url, page), mimetype='application/pdf', cache_timeout=60)

    return page

