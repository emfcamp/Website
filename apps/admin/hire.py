from flask import render_template

from sqlalchemy.sql.functions import func

from models.user import User
from models.product import ProductGroup, Product
from models.purchase import Purchase

from . import admin


def get_hires():
    purchases = (
        ProductGroup.query.filter_by(type="hire")
        .join(Product, Purchase, Purchase.owner)
        .group_by(User.id, Product.id, Purchase.state)
        .filter(Purchase.state.in_(["paid", "payment-pending"]))
        .with_entities(User, Product, Purchase.state, func.count(Purchase.id))
        .order_by(User.name, Product.name)
    )

    return purchases


@admin.route("/hire/all")
def hire():
    purchases = get_hires()
    return render_template("admin/hire/hire-purchases.html", purchases=purchases)
