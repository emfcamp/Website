import logging
import os.path
import shutil
from collections import namedtuple
from decimal import Decimal

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask import (
    current_app as app,
)
from flask_login import current_user, login_required
from sqlalchemy import select
from sqlalchemy.sql.functions import func
from wtforms import SubmitField, TextAreaField

from main import db, external_url
from models.product import PriceTier, Product
from models.purchase import Purchase

from ..common.epc import format_inline_epc_qr
from ..common.forms import Form
from ..common.receipt import render_pdf
from . import get_user_payment_or_abort, payments

logger = logging.getLogger(__name__)


class InvoiceForm(Form):
    company = TextAreaField("Company name")
    update = SubmitField("Update")


InvoiceLine = namedtuple(
    "InvoiceLine",
    [
        "price_tier",
        "quantity",
        "vat_rate",
        "vat_amount",
        "price",
    ],
)


@payments.route("/payment/<int:payment_id>/receipt", methods=["GET", "POST"])
@payments.route("/payment/<int:payment_id>/receipt.<string:fmt>")
@login_required
def invoice(payment_id, fmt=None):
    pdf = False
    if fmt == "pdf":
        pdf = True
    elif fmt:
        abort(404)

    payment = get_user_payment_or_abort(payment_id, allow_admin=True)

    form = InvoiceForm()

    if form.validate_on_submit():
        current_user.company = form.company.data
        payment.issue_vat_invoice_number()
        db.session.commit()

        flash("Company name updated")
        return redirect(url_for(".invoice", payment_id=payment_id))

    if request.method != "POST":
        form.company.data = current_user.company

    edit_company = bool(request.args.get("edit_company"))
    if request.args.get("js") == "0":
        flash("Please use your browser's print feature or download the PDF")

    price_tier_counts = (
        db.session.execute(
            select(Purchase)
            .filter_by(payment_id=payment_id)
            .join(PriceTier)
            .join(Product)
            .with_only_columns(PriceTier, func.count(Purchase.price_tier_id))
            .group_by(PriceTier.id, Product.name)
            .order_by(Product.name)
        )
        .tuples()
        .all()
    )

    invoice_lines = []
    prices = []
    for pt, count in price_tier_counts:
        price = pt.get_price(payment.currency)
        prices.append(
            {
                "sum_ex_vat": price.value_ex_vat * count,
                "sum_vat": price.vat * count,
            }
        )
        invoice_lines.append(
            InvoiceLine(
                price_tier=pt,
                quantity=count,
                vat_rate=pt.vat_rate,
                vat_amount=round((price.value - price.value_ex_vat) * count, 2),
                price=price,
            )
        )

    subtotal = sum(cost["sum_ex_vat"] for cost in prices)
    vat = sum(cost["sum_vat"] for cost in prices)

    # FIXME: we should use a currency-specific quantization here (or rounder numbers)
    if subtotal + vat - payment.amount > Decimal("0.01"):
        app.logger.error(
            "Invoice total mismatch: %s + %s - %s = %s",
            subtotal,
            vat,
            payment.amount,
            subtotal + vat - payment.amount,
        )
        flash("Your invoice cannot currently be displayed")
        return redirect(url_for("users.purchases"))

    if payment.vat_invoice_number:
        mode = "invoice"
        invoice_number = payment.issue_vat_invoice_number()
    else:
        mode = "receipt"
        invoice_number = None

    page = render_template(
        "payments/invoice.html",
        mode=mode,
        payment=payment,
        invoice_lines=invoice_lines,
        form=form,
        subtotal=subtotal,
        vat=vat,
        edit_company=edit_company,
        invoice_number=invoice_number,
        format_inline_epc_qr=format_inline_epc_qr,
    )

    url = external_url(".invoice", payment_id=payment_id)

    if pdf:
        return send_file(
            render_pdf(url, page),
            mimetype="application/pdf",
            max_age=60,
            download_name=f"emf_{mode}.pdf",
            as_attachment=True,
        )

    if mode == "invoice":
        invoice_dir = "/vat_invoices"
        if not os.path.exists(invoice_dir):
            logger.warning(
                "Not exporting VAT invoice as directory (%s) does not exist",
                invoice_dir,
            )
            return page

        with open(os.path.join(invoice_dir, f"{invoice_number}.pdf"), "wb") as f:
            shutil.copyfileobj(render_pdf(url, page), f)

    return page
