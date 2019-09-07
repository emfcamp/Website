from flask import render_template
from models.product import ProductGroup, PriceTier, Product
from models.purchase import Purchase
from decimal import Decimal
from collections import defaultdict

from . import admin


@admin.route("/reports/reconcile")
def report_reconcile():
    data = {}
    for pg in ProductGroup.query.all():
        if not pg.products:
            continue
        paid = defaultdict(Decimal)
        pending = defaultdict(Decimal)
        q = (
            Purchase.query.join(PriceTier, Product, ProductGroup)
            .filter(ProductGroup.id == Product.group_id)
            .filter(ProductGroup.id == pg.id)
        )

        for purchase in q.filter(Purchase.state.in_(("paid", "receipt-emailed"))):
            paid[purchase.price.currency] += purchase.price.value

        for purchase in q.filter(Purchase.state == "payment-pending"):
            pending[purchase.price.currency] += purchase.price.value

        data[pg.name] = {"paid": paid, "pending": pending}

    gt = {
        "paid": {"GBP": Decimal(), "EUR": Decimal()},
        "pending": {"GBP": Decimal(), "EUR": Decimal()},
    }
    for pg, totals in data.items():
        for typ in ("paid", "pending"):
            gt[typ]["GBP"] += totals[typ]["GBP"]
            gt[typ]["EUR"] += totals[typ]["EUR"]

    return render_template("admin/reports/reconcile.html", data=data, gt=gt)
