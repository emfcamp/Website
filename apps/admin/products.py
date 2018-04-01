# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals

from flask import (
    render_template, redirect, flash,
    url_for, current_app as app,
)
from flask_login import current_user

from wtforms.validators import Optional
from wtforms.widgets import TextArea
from wtforms import (
    SubmitField, BooleanField, StringField,
    DateField, IntegerField, DecimalField,
)

from sqlalchemy.sql.functions import func

from main import db, admin_new
from models.user import User
from models.product import (
    ProductGroup, Product, PriceTier, Price, ProductView, ProductViewProduct,
)
from models.purchase import (
    Purchase, PurchaseTransfer,
)
from ..common import require_permission
from ..common.flask_admin_base import AppModelView
from ..common.forms import Form, StaticField

from . import admin, admin_required


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


class EditProductForm(Form):
    name = StringField('Name')
    capacity_max = IntegerField('Maximum to sell')
    expires = DateField('Expiry Date (Optional)', [Optional()])
    personal_limit = IntegerField('Maximum to sell to an individual')
    price_gbp = StaticField('Price (GBP)')
    price_eur = StaticField('Price (EUR)')
    badge = BooleanField('Issue Badge')
    transferable = BooleanField('Transferable')
    description = StringField('Description', [Optional()], widget=TextArea())
    submit = SubmitField('Save')

    def init_with_product(self, product):
        self.name.data = product.name
        self.capacity_max.data = product.capacity_max
        self.expires.data = product.expires
        self.personal_limit.data = product.get_price_tier('standard').personal_limit
        self.price_gbp.data = product.get_price_tier('standard').get_price('GBP')
        self.price_eur.data = product.get_price_tier('standard').get_price('EUR')
        self.badge.data = product.get_attribute('badge')
        self.transferable.data = product.get_attribute('transferable')
        self.description.data = product.description

@admin.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@require_permission('arrivals')
def edit_product(product_id):
    form = EditProductForm()

    product = Product.query.get_or_404(product_id)
    if form.validate_on_submit():
        app.logger.info('%s editing product %s', current_user.name, product_id)
        for attr in ['name', 'capacity_max', 'expires', 'description']:
            cur_val = getattr(product, attr)
            new_val = getattr(form, attr).data

            if cur_val != new_val:
                app.logger.info(' %10s: %r -> %r', attr, cur_val, new_val)
                setattr(product, attr, new_val)

#        for attr in ['badge', 'transferable']
#
# 'personal_limit', price_gbp, price_eur

        db.session.commit()
        return redirect(url_for('.product_details', product_id=product_id))

    form.init_with_product(product)
    return render_template('admin/products/edit-product.html', product=product, form=form)


class NewProductForm(Form):
    name = StringField('Name')
    capacity_max = IntegerField('Maximum to sell')
    personal_limit = IntegerField('Maximum to sell to an individual')
    expires = DateField('Expiry Date (Optional)', [Optional()])
    price_gbp = DecimalField('Price (GBP)')
    price_eur = DecimalField('Price (EUR)')
    has_badge = BooleanField('Issue Badge')
    is_transferable = BooleanField('Transferable')
    description = StringField('Description', [Optional()], widget=TextArea())
    submit = SubmitField('Create')

    def init_with_product(self, product):
        self.name.data = product.name
        self.capacity_max.data = product.capacity_max
        self.personal_limit.data = product.personal_limit
        self.expires.data = product.expires
        self.has_badge.data = product.has_badge
        self.is_transferable.data = product.is_transferable
        self.price_gbp.data = product.get_price('GBP')
        self.price_eur.data = product.get_price('EUR')
        self.description.data = product.description

@admin.route('/new-product/', defaults={'copy_id': -1}, methods=['GET', 'POST'])
@admin.route('/new-product/<int:copy_id>', methods=['GET', 'POST'])
@admin_required
def new_product(copy_id):
    form = NewProductForm()

    if form.validate_on_submit():
        expires = form.expires.data if form.expires.data else None
        description = form.description.data if form.description.data else None

        pt = PriceTier(parent_id=form.parent_id.data,
                       name=form.name.data, expires=expires,
                       description=description,
                       personal_limit=form.personal_limit.data)

        #
        #               has_badge=form.has_badge.data,
        #               is_transferable=form.is_transferable.data)

        pt.prices = [Price('GBP', form.price_gbp.data),
                     Price('EUR', form.price_eur.data)]
        app.logger.info('%s adding new Product %s', current_user.name, pt)
        db.session.add(pt)
        db.session.commit()
        flash('Your new ticket product has been created')
        return redirect(url_for('.product_details', product_id=pt.id))

    if copy_id != -1:
        form.init_with_product(PriceTier.query.get(copy_id))

    return render_template('admin/products/new-product.html', product_id=copy_id, form=form)


@admin.route('/products/<int:product_id>')
@admin_required
def product_details(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('admin/products/product-details.html', product=product)



@admin.route('/products/price-tiers/<int:tier_id>')
@admin_required
def price_tier_details(tier_id):
    tier = PriceTier.query.get_or_404(tier_id)
    return render_template('admin/products/price-tier-details.html', tier=tier)


@admin.route('/products/group/<int:group_id>')
@admin_required
def product_group_details(group_id):
    group = ProductGroup.query.get_or_404(group_id)
    return render_template('admin/products/product-group-details.html', group=group)


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


