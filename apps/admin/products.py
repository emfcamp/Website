# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from . import admin, admin_required

from flask import (
    render_template, redirect, flash,
    url_for, current_app as app,
)
from flask_login import current_user

from wtforms.validators import Optional, Regexp
from wtforms.widgets import TextArea
from wtforms import (
    SubmitField, BooleanField, StringField, RadioField,
    DateField, IntegerField, DecimalField,
)

from sqlalchemy.sql.functions import func

from main import db
from models.user import User
from models.product import (
    ProductGroup, Product, PriceTier, Price,
)
from models.purchase import (
    Purchase, PurchaseTransfer,
)

from ..common import require_permission
from ..common.forms import Form, StaticField


@admin.route('/products')
@admin_required
def products():
    products = Product.query.all()
    return render_template('admin/products/products.html', products=products)


class EditProductForm(Form):
    name = StringField('Name')
    order = IntegerField('Order')
    type = StaticField('Type')
    capacity_limit = IntegerField('Maximum to sell')
    personal_limit = IntegerField('Maximum to sell to an individual')
    expires = DateField('Expiry Date (Optional)', [Optional()])
    price_gbp = StaticField('Price (GBP)')
    price_eur = StaticField('Price (EUR)')
    has_badge = BooleanField('Issue Badge')
    is_transferable = BooleanField('Transferable')
    discount_token = StringField('Discount token', [Optional(), Regexp('^[-_0-9a-zA-Z]+$')])
    description = StringField('Description', [Optional()], widget=TextArea())
    submit = SubmitField('Save')

    def init_with_product(self, product):
        self.name.data = product.name
        self.order.data = product.order
        self.type.data = product.type
        self.capacity_max.data = product.capacity_max
        self.personal_limit.data = product.personal_limit
        self.expires.data = product.expires
        self.price_gbp.data = product.get_price('GBP')
        self.price_eur.data = product.get_price('EUR')
        self.has_badge.data = product.has_badge
        self.is_transferable.data = product.is_transferable
        self.description.data = product.description
        self.discount_token.data = product.discount_token


@admin.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@require_permission('arrivals')
def edit_product(product_id):
    form = EditProductForm()

    product = Product.query.get_or_404(product_id)
    if form.validate_on_submit():
        app.logger.info('%s editing product %s', current_user.name, product_id)
        if form.discount_token.data == '':
            form.discount_token.data = None
        if form.description.data == '':
            form.description.data = None

        for attr in ['name', 'order', 'capacity_max', 'personal_limit', 'expires',
                     'has_badge', 'is_transferable', 'discount_token', 'description']:
            cur_val = getattr(product, attr)
            new_val = getattr(form, attr).data

            if cur_val != new_val:
                app.logger.info(' %10s: %r -> %r', attr, cur_val, new_val)
                setattr(product, attr, new_val)

        db.session.commit()
        return redirect(url_for('.product_details', product_id=product_id))

    form.init_with_product(product)
    return render_template('admin/products/edit-product.html', product=product, form=form)


class NewProductForm(Form):
    name = StringField('Name')
    order = IntegerField('Order')
    types = RadioField('Type')
    capacity_max = IntegerField('Maximum to sell')
    personal_limit = IntegerField('Maximum to sell to an individual')
    expires = DateField('Expiry Date (Optional)', [Optional()])
    price_gbp = DecimalField('Price (GBP)')
    price_eur = DecimalField('Price (EUR)')
    has_badge = BooleanField('Issue Badge')
    is_transferable = BooleanField('Transferable')
    discount_token = StringField('Discount token', [Optional(), Regexp('^[-_0-9a-zA-Z]+$')])
    description = StringField('Description', [Optional()], widget=TextArea())
    submit = SubmitField('Create')

    def init_with_ticket_product(self, ticket_product):
        self.name.data = ticket_product.name
        self.order.data = ticket_product.order
        self.admits.data = ticket_product.admits
        self.capacity_max.data = ticket_product.capacity_max
        self.personal_limit.data = ticket_product.personal_limit
        self.expires.data = ticket_product.expires
        self.has_badge.data = ticket_product.has_badge
        self.is_transferable.data = ticket_product.is_transferable
        self.price_gbp.data = ticket_product.get_price('GBP')
        self.price_eur.data = ticket_product.get_price('EUR')
        self.description.data = ticket_product.description
        self.discount_token.data = ticket_product.discount_token


@admin.route('/new-product/', defaults={'copy_id': -1}, methods=['GET', 'POST'])
@admin.route('/new-product/<int:copy_id>', methods=['GET', 'POST'])
@admin_required
def new_product(copy_id):
    form = NewProductForm()

    if form.validate_on_submit():
        expires = form.expires.data if form.expires.data else None
        token = form.discount_token.data if form.discount_token.data else None
        description = form.description.data if form.description.data else None

        pt = PriceTier(order=form.order.data, parent=form.admits.data,
                       name=form.name.data, expires=expires,
                       discount_token=token, description=description,
                       personal_limit=form.personal_limit.data,
                       has_badge=form.has_badge.data,
                       is_transferable=form.is_transferable.data)

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


# FIXME
@admin.route('/products/<int:product_id>/price-tiers/<int:tier_id>')
@admin_required
def price_tier_details(tier_id):
    tier = PriceTier.query.get_or_404(tier_id)
    return render_template('admin/products/price-tier-details.html', tier=tier)


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
                            .order_by(User.name, Product.order)

    return render_template('admin/products/furniture-purchases.html', purchases=purchases)


@admin.route('/tees')
@admin_required
def tees():
    purchases = ProductGroup.query.filter_by(name='tees') \
                            .join(Product, Purchase, Purchase.owner).group_by(User.id, Product.id) \
                            .with_entities(User, Product, func.count(Purchase.id)) \
                            .order_by(User.name, Product.order)

    return render_template('admin/products/tee-purchases.html', purchases=purchases)


