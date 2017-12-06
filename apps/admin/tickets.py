# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from . import admin, admin_required
from datetime import datetime

from Levenshtein import ratio, jaro
from flask import (
    render_template, redirect, request, flash,
    url_for, current_app as app, abort,
)
from flask_login import current_user
from flask_mail import Message

from wtforms.validators import Optional, Regexp, Required, Email, ValidationError
from wtforms.widgets import TextArea
from wtforms import (
    SubmitField, BooleanField, StringField, RadioField,
    DateField, IntegerField, DecimalField, FieldList, FormField,
)
from wtforms.fields.html5 import EmailField

from sqlalchemy.sql.functions import func

from main import db, mail
from models.exc import CapacityException
from models.user import User
from models.payment import Payment, BankPayment, BankTransaction
from models.product import (
    ProductGroup, Product, PriceTier, Price,
)
from models.purchase import (
    Purchase, Ticket, PurchaseTransfer, bought_states,
)

from ..common import require_permission, feature_enabled
from ..common.forms import Form, IntegerSelectField, HiddenIntegerField, StaticField
from ..common.receipt import attach_tickets


@admin.route('/transactions')
@admin_required
def transactions():
    txns = BankTransaction.query.filter_by(payment_id=None, suppressed=False).\
        order_by(BankTransaction.posted.desc())
    return render_template('admin/txns.html', txns=txns)


class TransactionSuppressForm(Form):
    suppress = SubmitField("Suppress")


@admin.route('/transaction/<int:txn_id>/suppress', methods=['GET', 'POST'])
@admin_required
def transaction_suppress(txn_id):
    txn = BankTransaction.query.get_or_404(txn_id)

    form = TransactionSuppressForm()
    if form.validate_on_submit():
        if form.suppress.data:
            txn.suppressed = True
            app.logger.info('Transaction %s suppressed', txn.id)

            db.session.commit()
            flash("Transaction %s suppressed" % txn.id)
            return redirect(url_for('admin.transactions'))

    return render_template('admin/txn-suppress.html', txn=txn, form=form)


@admin.route('/transactions/suppressed')
@admin_required
def suppressed():
    suppressed = BankTransaction.query.filter_by(suppressed=True).all()
    return render_template('admin/txns-suppressed.html', suppressed=suppressed)


def score_reconciliation(txn, payment):
    words = txn.payee.replace('-', ' ').split(' ')

    bankref_distances = [ratio(w, payment.bankref) for w in words]
    # Get the two best matches, for the two parts of the bankref
    bankref_score = sum(sorted(bankref_distances)[-2:])
    name_score = jaro(txn.payee, payment.user.name)

    other_score = 0.0

    if txn.amount == payment.amount:
        other_score += 0.4

    if txn.account.currency == payment.currency:
        other_score += 0.6

    # check posted against expiry?

    app.logger.debug('Scores for txn %s payment %s: %s %s %s',
                     txn.id, payment.id, bankref_score, name_score, other_score)
    return bankref_score + name_score + other_score


@admin.route('/transaction/<int:txn_id>/reconcile')
@admin_required
def transaction_suggest_payments(txn_id):
    txn = BankTransaction.query.get_or_404(txn_id)

    payments = BankPayment.query.filter_by(state='inprogress').order_by(BankPayment.bankref).all()
    payments = sorted(payments, key=lambda p: score_reconciliation(txn, p))
    payments = list(reversed(payments[-20:]))

    app.logger.info('Suggesting %s payments for txn %s', len(payments), txn.id)
    return render_template('admin/txn-suggest-payments.html', txn=txn, payments=payments)


class ManualReconcilePaymentForm(Form):
    reconcile = SubmitField("Reconcile")


@admin.route('/transaction/<int:txn_id>/reconcile/<int:payment_id>', methods=['GET', 'POST'])
@admin_required
def transaction_reconcile(txn_id, payment_id):
    txn = BankTransaction.query.get_or_404(txn_id)
    payment = BankPayment.query.get_or_404(payment_id)

    form = ManualReconcilePaymentForm()
    if form.validate_on_submit():
        if form.reconcile.data:
            app.logger.info("%s manually reconciling against payment %s (%s) by %s",
                            current_user.name, payment.id, payment.bankref, payment.user.email)

            if txn.payment:
                app.logger.error("Transaction already reconciled")
                flash("Transaction %s already reconciled" % txn.id)
                return redirect(url_for('admin.transactions'))

            if payment.state == 'paid':
                app.logger.error("Payment has already been paid")
                flash("Payment %s already paid" % payment.id)
                return redirect(url_for('admin.transactions'))

            txn.payment = payment
            payment.paid()
            db.session.commit()

            msg = Message("Electromagnetic Field ticket purchase update",
                          sender=app.config['TICKETS_EMAIL'],
                          recipients=[payment.user.email])

            msg.body = render_template("emails/tickets-paid-email-banktransfer.txt",
                                       user=payment.user, payment=payment)

            if feature_enabled('ISSUE_TICKETS'):
                attach_tickets(msg, payment.user)

            mail.send(msg)

            flash("Payment ID %s marked as paid" % payment.id)
            return redirect(url_for('admin.transactions'))

    return render_template('admin/txn-reconcile.html', txn=txn, payment=payment, form=form)


@admin.route('/tickets')
@admin.route('/tickets/paid')
@admin_required
def tickets():
    tickets = Ticket.query.filter_by(is_paid_for=True).order_by(Ticket.id).all()

    return render_template('admin/tickets.html', tickets=tickets)


@admin.route('/tickets/unpaid')
@admin_required
def tickets_unpaid():
    tickets = Purchase.query.filter_by(is_paid_for=False).order_by(Purchase.id).all()

    return render_template('admin/tickets.html', tickets=tickets)


@admin.route('/ticket-report')
def ticket_report():
    # This is an admissions-based view, so includes expired tickets
    totals = Ticket.query.outerjoin(Payment) \
        .filter(Ticket.state.in_(bought_states)) \
        .with_entities(PriceTier.name, func.count()) \
        .group_by(PriceTier.name).all()

    totals = dict(totals)

    query = Ticket.query.filter(is_paid_for=True).join(PriceTier, Price) \
        .with_entities(Product.name, func.count(), func.sum(Price.price_int)) \
        .group_by(Product.name)

    accounting_totals = {}
    for row in query.all():
        accounting_totals[row[0]] = {
            'count': row[1],
            'total': row[2]
        }

    return render_template('admin/ticket-report.html', totals=totals, accounting_totals=accounting_totals)


@admin.route('/products')
@admin_required
def products():
    products = Product.query.all()
    return render_template('admin/products.html', products=products)


class EditProductForm(Form):
    name = StringField('Name')
    order = IntegerField('Order')
    type = StaticField('Type')
    capacity_limit = IntegerField('Maximum tickets to sell')
    personal_limit = IntegerField('Maximum tickets to sell to an individual')
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
    return render_template('admin/edit-product.html', product=product, form=form)


class NewProductForm(Form):
    name = StringField('Name')
    order = IntegerField('Order')
    types = RadioField('Type')
    capacity_max = IntegerField('Maximum tickets to sell')
    personal_limit = IntegerField('Maximum tickets to sell to an individual')
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

    return render_template('admin/new-product.html', product_id=copy_id, form=form)


@admin.route('/products/<int:product_id>')
@admin_required
def product_details(product_id):
    product = Product.query.get_or_404(product_id)
    return render_template('admin/product-details.html', product=product)


# FIXME
@admin.route('/products/<int:product_id>/price-tiers/<int:tier_id>')
@admin_required
def price_tier_details(tier_id):
    tier = PriceTier.query.get_or_404(tier_id)
    return render_template('admin/price-tier-details.html', tier=tier)


class TicketAmountForm(Form):
    amount = IntegerSelectField('Number of tickets', [Optional()])
    tier_id = HiddenIntegerField('Price tier', [Required()])


class FreeTicketsForm(Form):
    price_tiers = FieldList(FormField(TicketAmountForm))
    allocate = SubmitField('Allocate tickets')


class FreeTicketsNewUserForm(FreeTicketsForm):
    name = StringField('Name', [Required()])
    email = EmailField('Email', [Email(), Required()])

    def validate_email(form, field):
        if User.does_user_exist(field.data):
            field.was_duplicate = True
            raise ValidationError('Account already exists')


@admin.route('/tickets/choose-free', methods=['GET', 'POST'])
@admin.route('/tickets/choose-free/<int:user_id>', methods=['GET', 'POST'])
@admin_required
def tickets_choose_free(user_id=None):
    has_price = Price.query.filter(Price.price_int > 0)

    free_pts = PriceTier.query.join(Product).filter(
        ~has_price.filter(Price.price_tier.expression).exists(),
    ).order_by(Product.order).all()

    if user_id is None:
        form = FreeTicketsNewUserForm()
        user = None
        new_user = True
    else:
        form = FreeTicketsForm()
        user = User.query.get_or_404(user_id)
        new_user = False

    if request.method != 'POST':
        for pt in free_pts:
            form.price_tiers.append_entry()
            form.price_tiers[-1].tier_id.data = pt.id

    pts = {pt.id: pt for pt in free_pts}
    for f in form.price_tiers:
        f._tier = pts[f.tier_id.data]
        # TODO: apply per-user limits
        values = range(f._tier.personal_limit + 1)
        f.amount.values = values
        f._any = any(values)

    if form.validate_on_submit():
        if new_user:
            app.logger.info('Creating new user with email %s and name %s',
                            form.email.data, form.name.data)
            user = User(form.email.data, form.name.data)
            flash('Created account for %s' % form.email.data)

        tickets = []
        for f in form.price_tiers:
            if f.amount.data:
                pt = f._tier
                for i in range(f.amount.data):
                    # FIXME use the proper method
                    try:
                        t = Purchase.create_instances(user=user, tier=pt, currency='GBP')
                    except CapacityException:
                        db.session.rollback()
                        raise

                    t.set_state('paid')
                    user.tickets.append(t)
                    tickets.append(t)

                app.logger.info('Allocated %s %s tickets to user', f.amount.data, pt.name)

        db.session.add(user)
        db.session.commit()

        code = user.login_code(app.config['SECRET_KEY'])
        msg = Message('Your complimentary tickets to EMF',
                      sender=app.config['TICKETS_EMAIL'],
                      recipients=[user.email])

        msg.body = render_template('emails/tickets-free.txt',
                            user=user, code=code, tickets=tickets,
                            new_user=new_user)

        if feature_enabled('ISSUE_TICKETS'):
            attach_tickets(msg, user)

        mail.send(msg)
        db.session.commit()

        flash('Allocated %s ticket(s)' % len(tickets))
        return redirect(url_for('.tickets_choose_free'))

    if new_user:
        users = User.query.order_by(User.id).all()
    else:
        users = None

    return render_template('admin/tickets-choose-free.html',
                           form=form, pts=free_pts, user=user, users=users)


@admin.route('/tickets/list-free')
@admin_required
def list_free_tickets():
    # Complimentary tickets and transferred tickets can both have no payment.
    # This page is actually intended to be a list of complimentary tickets.
    free_tickets = Purchase.query \
        .join(PriceTier) \
        .filter(
            Purchase.is_paid_for,
            Purchase.payment_id.is_(None),
            ~PurchaseTransfer.query.filter(PurchaseTransfer.ticket.expression).exists(),
        ).order_by(
            Purchase.user_id,
            ProductGroup.order
        ).all()

    return render_template('admin/tickets-list-free.html',
                           free_tickets=free_tickets)

class CancelTicketForm(Form):
    cancel = SubmitField("Cancel ticket")

@admin.route('/ticket/<int:ticket_id>/cancel-free', methods=['GET', 'POST'])
@admin_required
def cancel_free_ticket(ticket_id):
    ticket = Purchase.query.get_or_404(ticket_id)
    if ticket.payment is not None:
        abort(404)

    if not ticket.is_paid_for:
        app.logger.warn('Ticket %s is already cancelled', ticket.id)
        flash('This ticket is already cancelled')
        return redirect(url_for('admin.list_free_tickets'))

    form = CancelTicketForm()
    if form.validate_on_submit():
        if form.cancel.data:
            app.logger.info('Cancelling free ticket %s', ticket.id)
            now = datetime.utcnow()
            ticket.set_state('refunded')
            if ticket.expires is None or ticket.expires > now:
                ticket.expires = now

            db.session.commit()

            flash('Ticket cancelled')
            return redirect(url_for('admin.list_free_tickets'))

    return render_template('admin/ticket-cancel-free.html', ticket=ticket, form=form)


@admin.route('/transfers')
@admin_required
def ticket_transfers():
    transfer_logs = PurchaseTransfer.query.all()
    return render_template('admin/ticket-transfers.html', transfers=transfer_logs)


@admin.route('/furniture')
@admin_required
def furniture():
    purchases = ProductGroup.query.filter_by(name='furniture') \
                            .join(Product, Purchase, User).group_by(User.id, Product.id) \
                            .with_entities(User, Product, func.count(Purchase.id)) \
                            .order_by(User.name, Product.order)

    return render_template('admin/furniture-purchases.html', purchases=purchases)


@admin.route('/tees')
@admin_required
def tees():
    purchases = ProductGroup.query.filter_by(name='tees') \
                            .join(Product, Purchase, User).group_by(User.id, Product.id) \
                            .with_entities(User, Product, func.count(Purchase.id)) \
                            .order_by(User.name, Product.order)

    return render_template('admin/tee-purchases.html', purchases=purchases)


