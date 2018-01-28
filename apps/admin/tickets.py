# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from . import admin, admin_required

from flask import (
    render_template, redirect, request, flash,
    url_for, current_app as app, abort,
)
from flask_mail import Message

from wtforms.validators import Optional, Required, Email, ValidationError
from wtforms import (
    SubmitField, StringField,
    FieldList, FormField,
)
from wtforms.fields.html5 import EmailField

from sqlalchemy.sql.functions import func

from main import db, mail
from models.exc import CapacityException
from models.user import User
from models.payment import Payment
from models.product import (
    Product, PriceTier, Price,
)
from models.purchase import (
    Purchase, Ticket, PurchaseTransfer, bought_states,
)

from ..common import feature_enabled
from ..common.forms import Form, IntegerSelectField, HiddenIntegerField
from ..common.receipt import attach_tickets


@admin.route('/tickets')
@admin.route('/tickets/paid')
@admin_required
def tickets():
    tickets = Ticket.query.filter_by(is_paid_for=True).order_by(Ticket.id).all()

    return render_template('admin/tickets/tickets.html', tickets=tickets)


@admin.route('/tickets/unpaid')
@admin_required
def tickets_unpaid():
    tickets = Purchase.query.filter_by(is_paid_for=False) \
                            .filter(~Purchase.owner_id.is_(None)) \
                            .order_by(Purchase.id).all()

    return render_template('admin/tickets/tickets.html', tickets=tickets)


@admin.route('/ticket-report')
def ticket_report():
    # This is an admissions-based view, so includes expired tickets
    totals = Ticket.query.outerjoin(Payment) \
        .filter(Ticket.state.in_(bought_states)) \
        .with_entities(PriceTier.name, func.count()) \
        .group_by(PriceTier.name).all()

    totals = dict(totals)

    query = Ticket.query.filter_by(is_paid_for=True).join(PriceTier, Price) \
        .with_entities(Product.name, func.count(), func.sum(Price.price_int)) \
        .group_by(Product.name)

    accounting_totals = {}
    for row in query.all():
        accounting_totals[row[0]] = {
            'count': row[1],
            'total': row[2]
        }

    return render_template('admin/tickets/ticket-report.html', totals=totals, accounting_totals=accounting_totals)


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
    ).order_by(Product.name).all()

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
                        t = Purchase.create_purchases(user=user, tier=pt, currency='GBP')
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

    return render_template('admin/tickets/tickets-choose-free.html',
                           form=form, pts=free_pts, user=user, users=users)


@admin.route('/tickets/list-free')
@admin_required
def list_free_tickets():
    # Complimentary tickets and transferred tickets can both have no payment.
    # This page is actually intended to be a list of complimentary tickets.
    free_tickets = Purchase.query \
        .join(PriceTier, Product) \
        .filter(
            Purchase.is_paid_for,
            Purchase.payment_id.is_(None),
            ~PurchaseTransfer.query.filter(PurchaseTransfer.purchase.expression).exists(),
        ).order_by(
            Purchase.owner_id,
        ).all()

    return render_template('admin/tickets/tickets-list-free.html',
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
            ticket.cancel()

            db.session.commit()

            flash('Ticket cancelled')
            return redirect(url_for('admin.list_free_tickets'))

    return render_template('admin/tickets/ticket-cancel-free.html', ticket=ticket, form=form)


