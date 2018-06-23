# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from . import admin, admin_required

from flask import (
    render_template, redirect, flash,
    url_for, current_app as app, abort,
)
from flask_mail import Message

from main import db, mail
from models.exc import CapacityException
from models.user import User
from models.product import (
    ProductGroup, Product, PriceTier, Price,
)
from models.purchase import (
    Purchase, Ticket, PurchaseTransfer,
)

from .forms import (
    IssueTicketsInitialForm, IssueTicketsForm, IssueFreeTicketsNewUserForm,
    ReserveTicketsForm, ReserveTicketsNewUserForm, CancelTicketForm
)

from ..common import feature_enabled
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


@admin.route('/tickets/issue', methods=['GET', 'POST'])
@admin_required
def tickets_issue():
    form = IssueTicketsInitialForm()
    if form.validate_on_submit():
        if form.issue_free.data:
            return redirect(url_for('.tickets_issue_free', email=form.email.data))
        elif form.reserve.data:
            return redirect(url_for('.tickets_reserve', email=form.email.data))
    return render_template('admin/tickets/tickets-issue.html', form=form)


@admin.route('/tickets/issue-free/<email>', methods=['GET', 'POST'])
@admin_required
def tickets_issue_free(email):
    user = User.query.filter_by(email=email).one_or_none()

    if user is None:
        form = IssueFreeTicketsNewUserForm()
        new_user = True
    else:
        form = IssueTicketsForm()
        new_user = False

    free_pts = PriceTier.query.join(Product).filter(
        ~PriceTier.prices.any(Price.price_int > 0),
    ).order_by(Product.name).all()

    form.add_price_tiers(free_pts)

    if form.validate_on_submit():
        if not user:
            app.logger.info('Creating new user with email %s and name %s',
                            email, form.name.data)
            user = User(email, form.name.data)
            db.session.add(user)
            flash('Created account for %s' % email)

        basket = form.create_basket(user)
        app.logger.info('Admin basket for %s %s', user.email, basket)

        try:
            basket.create_purchases()
            basket.ensure_purchase_capacity()
            assert basket.total == 0

        except CapacityException as e:
            db.session.rollback()
            app.logger.warn('Limit exceeded creating admin tickets: %s', e)
            return redirect(url_for('.tickets_issue_free', email=email))

        for p in basket.purchases:
            p.set_state('paid')

        app.logger.info('Allocated %s tickets to user', len(basket.purchases))
        db.session.commit()

        code = user.login_code(app.config['SECRET_KEY'])
        msg = Message('Your complimentary tickets to Electromagnetic Field',
                      sender=app.config['TICKETS_EMAIL'],
                      recipients=[user.email])

        msg.body = render_template('emails/tickets-free.txt',
                            user=user, code=code, tickets=basket.purchases,
                            new_user=new_user)

        if feature_enabled('ISSUE_TICKETS'):
            attach_tickets(msg, user)

        mail.send(msg)
        db.session.commit()

        flash('Allocated %s ticket(s)' % len(basket.purchases))
        return redirect(url_for('.tickets_issue'))
    return render_template('admin/tickets/tickets-issue-free.html',
                           form=form, user=user, email=email)


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

@admin.route('/ticket/<int:ticket_id>/cancel-free', methods=['GET', 'POST'])
@admin_required
def cancel_free_ticket(ticket_id):
    ticket = Purchase.query.get_or_404(ticket_id)
    if ticket.payment is not None:
        abort(404)

    form = CancelTicketForm()
    if form.validate_on_submit():
        if form.cancel.data:
            app.logger.info('Cancelling free ticket %s', ticket.id)
            ticket.cancel()

            db.session.commit()

            flash('Ticket cancelled')
            return redirect(url_for('admin.list_free_tickets'))

    return render_template('admin/tickets/ticket-cancel-free.html', ticket=ticket, form=form)


@admin.route('/tickets/reserve/<email>', methods=['GET', 'POST'])
@admin_required
def tickets_reserve(email):
    user = User.query.filter_by(email=email).one_or_none()

    if user is None:
        form = ReserveTicketsNewUserForm()
        new_user = True
    else:
        form = ReserveTicketsForm()
        new_user = False

    pts = PriceTier.query.join(Product, ProductGroup) \
                         .order_by(ProductGroup.name, Product.display_name, Product.id).all()

    form.add_price_tiers(pts)

    if form.validate_on_submit():
        if not user:
            name = form.name.data

            app.logger.info('Creating new user with email %s and name %s', email, name)
            user = User(email, name)
            flash('Created account for %s' % name)
            db.session.add(user)

        basket = form.create_basket(user)

        app.logger.info('Admin basket for %s %s', user.email, basket)

        try:
            basket.create_purchases()
            basket.ensure_purchase_capacity()

            db.session.commit()

        except CapacityException as e:
            db.session.rollback()
            app.logger.warn('Limit exceeded creating admin tickets: %s', e)
            return redirect(url_for('.tickets_reserve', email=email))

        code = user.login_code(app.config['SECRET_KEY'])
        msg = Message('Your reserved tickets to EMF',
                      sender=app.config['TICKETS_EMAIL'],
                      recipients=[user.email])

        msg.body = render_template('emails/tickets-reserved.txt',
                            user=user, code=code, tickets=basket.purchases,
                            new_user=new_user, currency=form.currency.data)

        mail.send(msg)
        db.session.commit()

        flash('Reserved tickets and emailed {}'.format(user.email))
        return redirect(url_for('.tickets_issue'))

    return render_template('admin/tickets/tickets-reserve.html',
                           form=form, pts=pts, user=user)


