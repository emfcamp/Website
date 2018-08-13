from flask import render_template

from sqlalchemy.sql.functions import func

from models.map import MapObject
from models.user import User
from models.product import (
    ProductGroup, Product,
)
from models.purchase import Purchase

from . import admin

def get_hires():
    purchases = (ProductGroup.query.filter_by(type='hire')
                             .join(Product, Purchase, Purchase.owner)
                             .group_by(User.id, Product.id, Purchase.state)
                             .filter(Purchase.state.in_(['paid', 'payment-pending', 'receipt-emailed']))
                             .with_entities(User, Product, Purchase.state, func.count(Purchase.id))
                             .order_by(User.name, Product.name))

    return purchases


@admin.route('/hire/all')
def hire():
    purchases = get_hires()
    return render_template('admin/hire/hire-purchases.html', purchases=purchases)


@admin.route('/hire/hires-without-villages')
def hires_without_villages():
    purchases = get_hires()
    hires = (purchases.with_entities(User)
                      .group_by(User)
                      .from_self().outerjoin(User.map_objects)
                      .filter(MapObject.id.is_(None))
                      .group_by(User)
                      .with_entities(User))

    return render_template('admin/hire/hires-without-villages.html', hires=hires)

@admin.route('/hire/villages-without-hires')
def villages_without_hires():
    purchases = get_hires()
    purchase_users = (purchases.with_entities(User)
                               .group_by(User)
                               .subquery())

    villages = (MapObject.query.outerjoin(purchase_users)
                                    .filter(purchase_users.c.id.is_(None))
                                    .group_by(MapObject)
                                    .with_entities(MapObject))

    return render_template('admin/hire/villages-without-hires.html', villages=villages)



