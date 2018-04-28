# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals

from flask import (
    render_template, redirect, flash, request, abort,
    url_for, current_app as app,
)
from flask_login import current_user

from sqlalchemy.sql.functions import func

from main import db, admin_new
from models.user import User
from models.product import (
    ProductGroup, Product, PriceTier, Price, ProductView, ProductViewProduct,
)
from models.purchase import (
    Purchase, PurchaseTransfer,
)
from ..common.flask_admin_base import AppModelView

from . import admin, admin_required
from .forms import (EditProductForm, NewProductForm,
                    NewProductGroupForm, EditProductGroupForm, PriceTierForm)


admin_new.add_view(AppModelView(ProductGroup, db.session, category='Products'))
admin_new.add_view(AppModelView(Product, db.session, category='Products'))
admin_new.add_view(AppModelView(PriceTier, db.session, category='Products'))
admin_new.add_view(AppModelView(Price, db.session, category='Products'))
admin_new.add_view(AppModelView(ProductView, db.session, category='Products'))
admin_new.add_view(AppModelView(ProductViewProduct, db.session, category='Products'))

@admin.route('/products')
@admin_required
def products():
    root_groups = ProductGroup.query.filter_by(parent_id=None).order_by(ProductGroup.id).all()
    return render_template('admin/products/overview.html', root_groups=root_groups)


@admin.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_product(product_id):
    form = EditProductForm()

    product = Product.query.get_or_404(product_id)
    if form.validate_on_submit():
        app.logger.info('%s editing product %s', current_user.name, product_id)
        form.update_product(product)
        db.session.commit()
        return redirect(url_for('.product_details', product_id=product_id))

    form.init_with_product(product)
    return render_template('admin/products/edit-product.html', product=product, form=form)


@admin.route('/products/group/<int:parent_id>/new', defaults={'copy_id': None}, methods=['GET', 'POST'])
@admin.route('/products/<int:copy_id>/clone', defaults={'parent_id': None}, methods=['GET', 'POST'])
@admin_required
def new_product(copy_id, parent_id):
    if parent_id:
        parent = ProductGroup.query.get_or_404(parent_id)
    else:
        parent = Product.query.get(copy_id).parent

    form = NewProductForm()

    if form.validate_on_submit():
        product = Product(parent=parent,
                       name=form.name.data,
                       expires=form.expires.data or None,
                       capacity_max=form.capacity_max.data or None,
                       description=form.description.data or None)
        app.logger.info('%s adding new Product %s', current_user.name, product)
        db.session.add(product)
        db.session.commit()
        flash('Your new ticket product has been created')
        return redirect(url_for('.product_details', product_id=product.id))

    if copy_id:
        form.init_with_product(Product.query.get(copy_id))

    return render_template('admin/products/new-product.html', parent=parent, product_id=copy_id, form=form)


@admin.route('/products/<int:product_id>')
@admin_required
def product_details(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('admin/products/product-details.html', product=product)


@admin.route('/products/<int:product_id>/new-tier', methods=['GET', 'POST'])
@admin_required
def new_price_tier(product_id):
    form = PriceTierForm()
    product = Product.query.get_or_404(product_id)

    if form.validate_on_submit():
        pt = PriceTier(form.name.data)
        pt.prices = [Price('GBP', form.price_gbp.data),
                     Price('EUR', form.price_eur.data)]

        # Only activate this price tier if it's the first one added.
        pt.active = (len(product.price_tiers) == 0)
        product.price_tiers.append(pt)
        db.session.commit()
        return redirect(url_for('.price_tier_details', tier_id=pt.id))

    return render_template('admin/products/price-tier-new.html', product=product, form=form)


@admin.route('/products/price-tiers/<int:tier_id>')
@admin_required
def price_tier_details(tier_id):
    tier = PriceTier.query.get_or_404(tier_id)
    return render_template('admin/products/price-tier-details.html', tier=tier)


@admin.route('/products/price-tiers/<int:tier_id>', methods=['POST'])
@admin_required
def price_tier_modify(tier_id):
    tier = PriceTier.query.get_or_404(tier_id)
    if request.form.get('delete') and tier.unused:
        db.session.delete(tier)
        db.session.commit()
        flash("Price tier deleted")
        return redirect(url_for('.price_tier_details', tier_id=tier.id))

    if request.form.get('activate'):
        for t in tier.parent.price_tiers:
            t.active = False

        tier.active = True
        db.session.commit()
        flash("Price tier activated")
        return redirect(url_for('.price_tier_details', tier_id=tier.id))

    if request.form.get('deactivate'):
        tier.active = False
        db.session.commit()
        flash("Price tier deactivated")
        return redirect(url_for('.price_tier_details', tier_id=tier.id))

    return abort(401)


@admin.route('/products/group/<int:group_id>')
@admin_required
def product_group_details(group_id):
    group = ProductGroup.query.get_or_404(group_id)
    return render_template('admin/products/product-group-details.html', group=group)


@admin.route('/products/group/new', methods=['GET', 'POST'])
@admin_required
def product_group_new():
    if request.args.get('parent'):
        parent = ProductGroup.query.get_or_404(request.args.get('parent'))
    else:
        parent = None

    form = NewProductGroupForm()

    if form.validate_on_submit():
        pg = ProductGroup(form.type.data, parent, parent.id if parent else None,
                          name=form.name.data, capacity_max=form.capacity_max.data,
                          expires=form.expires.data)
        app.logger.info('%s adding new ProductGroup %s', current_user.name, pg)
        db.session.add(pg)
        db.session.commit()
        flash("ProductGroup created")
        return redirect(url_for('.product_group_details', group_id=pg.id))

    return render_template('admin/products/product-group-edit.html',
                           method='new', parent=parent, form=form)


@admin.route('/products/group/<int:group_id>/edit', methods=['GET', 'POST'])
@admin_required
def product_group_edit(group_id):
    group = ProductGroup.query.get_or_404(group_id)
    form = EditProductGroupForm()
    if form.validate_on_submit():
        group = form.update_pg(group)
        db.session.add(group)
        db.session.commit()
        flash("ProductGroup updated")
        return redirect(url_for('.product_group_details', group_id=group.id))

    form.init_with_pg(group)

    return render_template('admin/products/product-group-edit.html',
                           method='edit', group=group, form=form)


@admin.route('/transfers')
@admin_required
def purchase_transfers():
    transfer_logs = PurchaseTransfer.query.all()
    return render_template('admin/products/purchase-transfers.html', transfers=transfer_logs)


@admin.route('/furniture')
@admin_required
def furniture():
    purchases = ProductGroup.query.filter_by(name='furniture') \
                            .join(Product, Purchase, Purchase.owner).group_by(User.id, Product.id) \
                            .with_entities(User, Product, func.count(Purchase.id)) \
                            .order_by(User.name)

    return render_template('admin/products/furniture-purchases.html', purchases=purchases)


@admin.route('/tees')
@admin_required
def tees():
    purchases = ProductGroup.query.filter_by(name='tees') \
                            .join(Product, Purchase, Purchase.owner).group_by(User.id, Product.id) \
                            .with_entities(User, Product, func.count(Purchase.id)) \
                            .order_by(User.name)

    return render_template('admin/products/tee-purchases.html', purchases=purchases)
