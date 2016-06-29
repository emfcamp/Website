from datetime import datetime, timedelta

from Levenshtein import ratio, jaro
from flask import (
    render_template, redirect, request, flash,
    url_for, abort, current_app as app, Blueprint
)
from flask.ext.login import current_user
from flask_mail import Message

from wtforms.validators import Optional, Regexp, Required, Email, ValidationError
from wtforms.widgets import TextArea
from wtforms import (
    SubmitField, BooleanField, StringField, RadioField, HiddenField,
    DateField, IntegerField, DecimalField, FieldList, FormField, SelectField,
)
from wtforms.fields.html5 import EmailField

from sqlalchemy import or_
from sqlalchemy.orm import joinedload
from sqlalchemy.sql.functions import func

from main import db, mail, stripe
from models.user import User
from models.permission import Permission
from models.payment import (
    Payment, BankPayment, BankRefund, StripeRefund,
    BankTransaction, StateException,
)
from models.ticket import (
    Ticket, TicketCheckin, TicketType, TicketPrice, TicketTransfer
)
from models.cfp import Proposal
from models.feature_flag import FeatureFlag, DB_FEATURE_FLAGS, refresh_flags
from models.site_state import SiteState, VALID_STATES, refresh_states
from .common import require_permission, send_template_email
from .common.forms import Form, IntegerSelectField, HiddenIntegerField, StaticField
from .payments.stripe import (
    StripeUpdateUnexpected, StripeUpdateConflict, stripe_update_payment,
    stripe_payment_refunded,
)

admin = Blueprint('admin', __name__)

admin_required = require_permission('admin')  # Decorator to require admin permissions


@admin.context_processor
def admin_variables():
    if not request.path.startswith('/admin'):
        return {}

    unreconciled_count = BankTransaction.query.filter_by(payment_id=None, suppressed=False).count()

    expiring_count = BankPayment.query.join(Ticket).filter(
        BankPayment.state == 'inprogress',
        Ticket.expires < datetime.utcnow() + timedelta(days=3),
    ).group_by(BankPayment.id).count()

    return {'unreconciled_count': unreconciled_count,
            'expiring_count': expiring_count,
            'view_name': request.url_rule.endpoint.replace('admin.', '.')}


@admin.route("/stats")
def stats():
    # Don't care about the state of the payment if it's paid for
    paid = Ticket.query.filter_by(paid=True)

    parking_paid = paid.join(TicketType).filter_by(admits='car')
    campervan_paid = paid.join(TicketType).filter_by(admits='campervan')

    # For new payments, the user hasn't committed to paying yet
    unpaid = Payment.query.filter(
        Payment.state != 'new',
        Payment.state != 'cancelled'
    ).join(Ticket).filter_by(paid=False)

    expired = unpaid.filter_by(expired=True)
    unexpired = unpaid.filter_by(expired=False)

    # Providers who take a while to clear - don't care about captured Stripe payments
    gocardless_unpaid = unpaid.filter(Payment.provider == 'gocardless',
                                      Payment.state == 'inprogress')
    banktransfer_unpaid = unpaid.filter(Payment.provider == 'banktransfer',
                                        Payment.state == 'inprogress')

    # TODO: remove this if it's not needed
    full_gocardless_unexpired = unexpired.filter(Payment.provider == 'gocardless',
                                                 Payment.state == 'inprogress'). \
                                                 join(TicketType).filter_by(admits='full')
    full_banktransfer_unexpired = unexpired.filter(Payment.provider == 'banktransfer',
                                                   Payment.state == 'inprogress'). \
                                                   join(TicketType).filter_by(admits='full')

    # These are people queries - don't care about cars or campervans being checked in
    checked_in = Ticket.query.filter(TicketType.admits.in_(['full', 'kid'])) \
                             .join(TicketCheckin).filter_by(checked_in=True)
    badged_up = TicketCheckin.query.filter_by(badged_up=True)

    users = User.query

    proposals = Proposal.query

    # Simple count queries
    queries = [
        'checked_in', 'badged_up',
        'users',
        'proposals',
        'gocardless_unpaid', 'banktransfer_unpaid',
        'full_gocardless_unexpired', 'full_banktransfer_unexpired',
    ]
    stats = ['%s:%s' % (q, locals()[q].count()) for q in queries]

    # Admission types breakdown
    admit_types = ['full', 'kid', 'campervan', 'car']
    admit_totals = dict.fromkeys(admit_types, 0)

    for query in 'paid', 'expired', 'unexpired':
        tickets = locals()[query].join(TicketType).with_entities(
            TicketType.admits,
            func.count(),
        ).group_by(TicketType.admits).all()
        tickets = dict(tickets)

        for a in admit_types:
            stats.append('%s_%s:%s' % (a, query, tickets.get(a, 0)))
            admit_totals[a] += tickets.get(a, 0)

    # and totals
    for a in admit_types:
        stats.append('%s:%s' % (a, admit_totals[a]))


    return ' '.join(stats)


@admin.route('/')
@admin_required
def home():
    return render_template('admin/admin.html')


@admin.route('/transactions')
@admin_required
def transactions():
    txns = BankTransaction.query.filter_by(payment_id=None, suppressed=False).order_by(BankTransaction.posted.desc())
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
            mail.send(msg)

            flash("Payment ID %s marked as paid" % payment.id)
            return redirect(url_for('admin.transactions'))

    return render_template('admin/txn-reconcile.html', txn=txn, payment=payment, form=form)


@admin.route('/tickets')
@admin_required
def tickets():
    tickets = Ticket.query.filter(
        Ticket.paid,
    ).order_by(Ticket.id).all()

    return render_template('admin/tickets.html', tickets=tickets)

@admin.route('/tickets/unpaid')
@admin_required
def tickets_unpaid():
    tickets = Ticket.query.filter(
        ~Ticket.paid,
    ).order_by(Ticket.id).all()

    return render_template('admin/tickets.html', tickets=tickets)


@admin.route('/ticket-types')
@admin_required
def ticket_types():
    # This is an admissions-based view, so includes expired tickets
    totals = Ticket.query.outerjoin(Payment).filter(
        Ticket.refund_id.is_(None),
        or_(Ticket.paid == True,  # noqa
            ~Payment.state.in_(['new', 'cancelled']))
    ).join(TicketType).with_entities(
        TicketType.admits,
        func.count(),
    ).group_by(TicketType.admits).all()

    totals = dict(totals)
    types = TicketType.query.all()
    return render_template('admin/ticket-types.html', ticket_types=types, totals=totals)

ADMITS_LABELS = [('full', 'Adult'), ('kid', 'Under 16'),
                 ('campervan', 'Campervan'), ('car', 'Car'),
                 ('other', 'Other')]

class EditTicketTypeForm(Form):
    name = StringField('Name')
    order = IntegerField('Order')
    admits = StaticField('Admits')
    type_limit = IntegerField('Maximum tickets to sell')
    personal_limit = IntegerField('Maximum tickets to sell to an individual')
    expires = DateField('Expiry Date (Optional)', [Optional()])
    price_gbp = StaticField('Price (GBP)')
    price_eur = StaticField('Price (EUR)')
    has_badge = BooleanField('Issue Badge')
    is_transferable = BooleanField('Transferable')
    discount_token = StringField('Discount token', [Optional(), Regexp('^[-_0-9a-zA-Z]+$')])
    description = StringField('Description', [Optional()], widget=TextArea())
    submit = SubmitField('Save')

    def init_with_ticket_type(self, ticket_type):
        self.name.data = ticket_type.name
        self.order.data = ticket_type.order
        self.admits.data = dict(ADMITS_LABELS)[ticket_type.admits]
        self.type_limit.data = ticket_type.type_limit
        self.personal_limit.data = ticket_type.personal_limit
        self.expires.data = ticket_type.expires
        self.price_gbp.data = ticket_type.get_price('GBP')
        self.price_eur.data = ticket_type.get_price('EUR')
        self.has_badge.data = ticket_type.has_badge
        self.is_transferable.data = ticket_type.is_transferable
        self.description.data = ticket_type.description
        self.discount_token.data = ticket_type.discount_token


@admin.route('/ticket-types/<int:type_id>/edit', methods=['GET', 'POST'])
@require_permission('arrivals')
def edit_ticket_type(type_id):
    form = EditTicketTypeForm()

    ticket_type = TicketType.query.get_or_404(type_id)
    if form.validate_on_submit():
        app.logger.info('%s editing ticket type %s', current_user.name, type_id)
        if form.discount_token.data == '':
            form.discount_token.data = None
        if form.description.data == '':
            form.description.data = None

        for attr in ['name', 'order', 'type_limit', 'personal_limit', 'expires',
                     'has_badge', 'is_transferable', 'discount_token', 'description']:
            cur_val = getattr(ticket_type, attr)
            new_val = getattr(form, attr).data

            if cur_val != new_val:
                app.logger.info(' %10s: %r -> %r', attr, cur_val, new_val)
                setattr(ticket_type, attr, new_val)

        db.session.commit()
        return redirect(url_for('.ticket_type_details', type_id=type_id))

    form.init_with_ticket_type(ticket_type)
    return render_template('admin/edit-ticket-type.html', ticket_type=ticket_type, form=form)


class NewTicketTypeForm(Form):
    name = StringField('Name')
    order = IntegerField('Order')
    admits = RadioField('Admits', choices=ADMITS_LABELS)
    type_limit = IntegerField('Maximum tickets to sell')
    personal_limit = IntegerField('Maximum tickets to sell to an individual')
    expires = DateField('Expiry Date (Optional)', [Optional()])
    price_gbp = DecimalField('Price (GBP)')
    price_eur = DecimalField('Price (EUR)')
    has_badge = BooleanField('Issue Badge')
    is_transferable = BooleanField('Transferable')
    discount_token = StringField('Discount token', [Optional(), Regexp('^[-_0-9a-zA-Z]+$')])
    description = StringField('Description', [Optional()], widget=TextArea())
    submit = SubmitField('Create')

    def init_with_ticket_type(self, ticket_type):
        self.name.data = ticket_type.name
        self.order.data = ticket_type.order
        self.admits.data = ticket_type.admits
        self.type_limit.data = ticket_type.type_limit
        self.personal_limit.data = ticket_type.personal_limit
        self.expires.data = ticket_type.expires
        self.has_badge.data = ticket_type.has_badge
        self.is_transferable.data = ticket_type.is_transferable
        self.price_gbp.data = ticket_type.get_price('GBP')
        self.price_eur.data = ticket_type.get_price('EUR')
        self.description.data = ticket_type.description
        self.discount_token.data = ticket_type.discount_token


@admin.route('/new-ticket-type/', defaults={'copy_id': -1}, methods=['GET', 'POST'])
@admin.route('/new-ticket-type/<int:copy_id>', methods=['GET', 'POST'])
@admin_required
def new_ticket_type(copy_id):
    form = NewTicketTypeForm()

    if form.validate_on_submit():
        expires = form.expires.data if form.expires.data else None
        token = form.discount_token.data if form.discount_token.data else None
        description = form.description.data if form.description.data else None

        tt = TicketType(form.order.data, form.admits.data,
                        form.name.data, form.type_limit.data, expires=expires,
                        discount_token=token, description=description,
                        personal_limit=form.personal_limit.data,
                        has_badge=form.has_badge.data,
                        is_transferable=form.is_transferable.data)

        tt.prices = [TicketPrice('GBP', form.price_gbp.data),
                     TicketPrice('EUR', form.price_eur.data)]
        app.logger.info('%s adding new TicketType %s', current_user.name, tt)
        db.session.add(tt)
        db.session.commit()
        flash('Your new ticket type has been created')
        return redirect(url_for('.ticket_type_details', type_id=tt.id))

    if copy_id != -1:
        form.init_with_ticket_type(TicketType.query.get(copy_id))

    return render_template('admin/new-ticket-type.html', ticket_type_id=copy_id, form=form)


@admin.route('/ticket-types/<int:type_id>')
@admin_required
def ticket_type_details(type_id):
    ticket_type = TicketType.query.get_or_404(type_id)
    return render_template('admin/ticket-type-details.html', ticket_type=ticket_type)


class TicketAmountForm(Form):
    amount = IntegerSelectField('Number of tickets', [Optional()])
    type_id = HiddenIntegerField('Ticket Type', [Required()])

class FreeTicketsForm(Form):
    types = FieldList(FormField(TicketAmountForm))
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
    has_price = TicketPrice.query.filter(TicketPrice.price_int > 0)

    free_tts = TicketType.query.filter(
        ~has_price.filter(TicketPrice.type.expression).exists(),
    ).order_by(TicketType.order).all()

    if user_id is None:
        form = FreeTicketsNewUserForm()
        user = None
        new_user = True
    else:
        form = FreeTicketsForm()
        user = User.query.get_or_404(user_id)
        new_user = False

    if request.method != 'POST':
        for tt in free_tts:
            form.types.append_entry()
            form.types[-1].type_id.data = tt.id

    tts = {tt.id: tt for tt in free_tts}
    for f in form.types:
        f._type = tts[f.type_id.data]
        # TODO: apply per-user limits
        values = range(f._type.personal_limit + 1)
        f.amount.values = values
        f._any = any(values)

    if form.validate_on_submit():
        if new_user:
            app.logger.info('Creating new user with email %s and name %s',
                             form.email.data, form.name.data)
            user = User(form.email.data, form.name.data)
            flash('Created account for %s' % form.email.data)

        tickets = []
        for f in form.types:
            if f.amount.data:
                tt = f._type
                for i in range(f.amount.data):
                    t = Ticket(type=tt, user_id=user_id)
                    t.paid = True
                    user.tickets.append(t)
                    tickets.append(t)

                app.logger.info('Allocated %s %s tickets to user', f.amount.data, tt.name)

        db.session.add(user)
        db.session.commit()

        code = user.login_code(app.config['SECRET_KEY'])
        send_template_email('Your complimentary tickets to EMF',
                            user.email, app.config['CONTACT_EMAIL'],
                            'emails/tickets-free.txt',
                            user=user, code=code, tickets=tickets,
                            new_user=new_user)

        flash('Allocated %s ticket(s)' % len(tickets))
        return redirect(url_for('.tickets_choose_free'))

    if new_user:
        users = User.query.order_by(User.id).all()
    else:
        users = None

    return render_template('admin/tickets-choose-free.html',
                           form=form, tts=free_tts, user=user, users=users)

@admin.route('/tickets/list-free')
@admin_required
def list_free_tickets():
    # Complimentary tickets and transferred tickets can both have no payment.
    # This page is actually intended to be a list of complimentary tickets.
    free_tickets = Ticket.query \
        .join(TicketType) \
        .filter(
            Ticket.paid,
            Ticket.payment_id.is_(None),
            ~TicketTransfer.query.filter(TicketTransfer.ticket.expression).exists(),
        ).order_by(
            Ticket.user_id,
            TicketType.order
        ).all()

    return render_template('admin/tickets-list-free.html',
                           free_tickets=free_tickets)


@admin.route('/transfers')
@admin_required
def ticket_transfers():
    transfer_logs = TicketTransfer.query.all()
    return render_template('admin/ticket-transfers.html', transfers=transfer_logs)


class NewUserForm(Form):
    name = StringField('Name', [Required()])
    email = EmailField('Email', [Email(), Required()])
    add = SubmitField('Add User')

    def validate_email(form, field):
        if User.does_user_exist(field.data):
            field.was_duplicate = True
            raise ValidationError('Account already exists')


@admin.route("/users", methods=['GET', 'POST'])
@admin_required
def users():
    form = NewUserForm()

    if form.validate_on_submit():
        email, name = form.email.data, form.name.data
        user = User(email, name)

        db.session.add(user)
        db.session.commit()
        app.logger.info('%s manually created new user with email %s and id: %s',
                         current_user.id, email, user.id)

        code = user.login_code(app.config['SECRET_KEY'])
        send_template_email('Welcome to the EMF website',
                            email, app.config['CONTACT_EMAIL'],
                            'emails/manually_added_user.txt',
                            user=user, code=code)

        flash('Created account for: %s' % name)
        return redirect(url_for('.users'))

    users = User.query.order_by(User.id).options(joinedload(User.permissions)).all()
    return render_template('admin/users.html', users=users, form=form)


@admin.route("/users/<int:user_id>", methods=['GET', 'POST'])
@admin_required
def user(user_id):
    user = User.query.filter_by(id=user_id).one()
    permissions = Permission.query.all()

    class PermissionsForm(Form):
        change = SubmitField('Change')

    for permission in permissions:
        setattr(PermissionsForm, "permission_" + permission.name,
                BooleanField(permission.name, default=user.has_permission(permission.name, False)))

    form = PermissionsForm()

    if request.method == 'POST' and form.validate():
        for permission in permissions:
            field = getattr(form, "permission_" + permission.name)
            if user.has_permission(permission.name, False) != field.data:
                app.logger.info("user %s (%s) %s: %s -> %s",
                                user.name,
                                user.id,
                                permission.name,
                                user.has_permission(permission.name, False),
                                field.data)

                if field.data:
                    user.grant_permission(permission.name)
                else:
                    user.revoke_permission(permission.name)

                db.session.commit()

        return redirect(url_for('.user', user_id=user.id))
    return render_template('admin/user.html',
                           user=user,
                           form=form,
                           permissions=permissions)


@admin.route('/payments')
@admin_required
def payments():
    payments = Payment.query.join(Ticket).with_entities(
        Payment,
        func.min(Ticket.expires).label('first_expires'),
        func.count(Ticket.id).label('ticket_count'),
    ).group_by(Payment).order_by(Payment.id).all()

    return render_template('admin/payments.html', payments=payments)


@admin.route('/payments/expiring')
@admin_required
def expiring():
    expiring = BankPayment.query.join(Ticket).filter(
        BankPayment.state == 'inprogress',
        Ticket.expires < datetime.utcnow() + timedelta(days=3),
    ).with_entities(
        BankPayment,
        func.min(Ticket.expires).label('first_expires'),
        func.count(Ticket.id).label('ticket_count'),
    ).group_by(BankPayment).order_by('first_expires').all()

    return render_template('admin/payments-expiring.html', expiring=expiring)


class ResetExpiryForm(Form):
    reset = SubmitField("Reset")


@admin.route('/payment/<int:payment_id>/reset-expiry', methods=['GET', 'POST'])
@admin_required
def reset_expiry(payment_id):
    payment = BankPayment.query.get_or_404(payment_id)

    form = ResetExpiryForm()
    if form.validate_on_submit():
        if form.reset.data:
            app.logger.info("%s manually extending expiry for payment %s", current_user.name, payment.id)
            for t in payment.tickets:
                if payment.currency == 'GBP':
                    t.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS_TRANSFER'))
                elif payment.currency == 'EUR':
                    t.expires = datetime.utcnow() + timedelta(
                        days=app.config.get('EXPIRY_DAYS_TRANSFER_EURO'))
                app.logger.info("Reset expiry for ticket %s", t.id)

            db.session.commit()

            flash("Expiry reset for payment %s" % payment.id)
            return redirect(url_for('admin.expiring'))

    return render_template('admin/payment-reset-expiry.html', payment=payment, form=form)


class SendReminderForm(Form):
    remind = SubmitField("Send reminder")


@admin.route('/payment/<int:payment_id>/reminder', methods=['GET', 'POST'])
@admin_required
def send_reminder(payment_id):
    payment = BankPayment.query.get_or_404(payment_id)

    form = SendReminderForm()
    if form.validate_on_submit():
        if form.remind.data:
            app.logger.info("%s sending reminder email to %s <%s> for payment %s",
                            current_user.name, payment.user.name, payment.user.email, payment.id)

            if payment.reminder_sent:
                app.logger.error('Reminder for payment %s already sent', payment.id)
                flash("Cannot send duplicate reminder email for payment %s" % payment.id)
                return redirect(url_for('admin.expiring'))

            msg = Message("Electromagnetic Field ticket purchase update",
                          sender=app.config['TICKETS_EMAIL'],
                          recipients=[payment.user.email])
            msg.body = render_template("emails/tickets-reminder.txt", payment=payment)
            mail.send(msg)

            payment.reminder_sent = True
            db.session.commit()

            flash("Reminder email for payment %s sent" % payment.id)
            return redirect(url_for('admin.expiring'))

    return render_template('admin/payment-send-reminder.html', payment=payment, form=form)


class UpdatePaymentForm(Form):
    update = SubmitField("Update payment")


@admin.route('/payment/<int:payment_id>/update', methods=['GET', 'POST'])
@admin_required
def update_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    if payment.provider != 'stripe':
        abort(404)

    form = UpdatePaymentForm()
    if form.validate_on_submit():
        if form.update.data:
            app.logger.info('Requesting updated status for %s payment %s', payment.provider, payment.id)

            try:
                stripe_update_payment(payment)
            except StripeUpdateConflict:
                flash('Unable to update due to a status conflict')
                return redirect(url_for('admin.update_payment', payment_id=payment.id))
            except StripeUpdateUnexpected:
                flash('Unable to update due to an unexpected response from Stripe')
                return redirect(url_for('admin.update_payment', payment_id=payment.id))

            flash('Payment status updated')
            return redirect(url_for('admin.update_payment', payment_id=payment.id))

    return render_template('admin/payment-update.html', payment=payment, form=form)


class CancelPaymentForm(Form):
    cancel = SubmitField("Cancel payment")


@admin.route('/payment/<int:payment_id>/cancel', methods=['GET', 'POST'])
@admin_required
def cancel_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    if payment.provider == u'stripe':
        msg = 'Cannot cancel stripe payment (id: %s).' % payment_id
        app.logger.warn(msg)
        flash(msg)
        return redirect(url_for('admin.payments'))

    form = CancelPaymentForm()
    if form.validate_on_submit():
        if form.cancel.data and (payment.provider in ['banktransfer', 'gocardless']):
            app.logger.info("%s manually cancelling payment %s", current_user.name, payment.id)
            try:
                payment.cancel()
            except StateException, e:
                msg = 'Could not cancel payment %s: %s' % (payment_id, e)
                app.logger.warn(msg)
                flash(msg)
                return redirect(url_for('admin.payments'))

            db.session.commit()

            flash("Payment %s cancelled" % payment.id)
            return redirect(url_for('admin.expiring'))

    return render_template('admin/payment-cancel.html', payment=payment, form=form)


class RefundPaymentForm(Form):
    refund = SubmitField("Refund payment")

@admin.route('/payment/<int:payment_id>/full-refund', methods=['GET', 'POST'])
@admin_required
def refund_payment(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    form = RefundPaymentForm()
    if form.validate_on_submit():
        if form.refund.data:
            app.logger.info("Manually refunding payment %s", payment.id)
            try:
                payment.manual_refund()

            except StateException, e:
                app.logger.warn('Could not refund payment %s: %s', payment_id, e)
                flash('Could not refund payment due to a state error')
                return redirect(url_for('admin.payments'))

            db.session.commit()

            flash("Payment refunded")
            return redirect(url_for('admin.payments'))

    return render_template('admin/payment-refund.html', payment=payment, form=form)



class PartialRefundTicketForm(Form):
    ticket_id = HiddenIntegerField('Ticket ID', [Required()])
    refund = BooleanField('Refund ticket', default=True)

class PartialRefundForm(Form):
    tickets = FieldList(FormField(PartialRefundTicketForm))
    refund = SubmitField('I have refunded these tickets by bank transfer')
    stripe_refund = SubmitField('Refund through Stripe')


@admin.route("/payment/<int:payment_id>/refund", methods=['GET', 'POST'])
@admin_required
def partial_refund(payment_id):
    payment = Payment.query.get_or_404(payment_id)

    valid_states = ['charged', 'paid', 'partrefunded']
    if payment.state not in valid_states:
        app.logger.warning("Payment %s is %s, not one of %s", payment_id, payment.state, valid_states)
        flash('Payment is not currently refundable')
        return redirect(url_for('.payments'))

    form = PartialRefundForm(request.form)

    if payment.provider != 'stripe':
        form.stripe_refund.data = ''

    if request.method != 'POST':
        for ticket in payment.tickets:
            form.tickets.append_entry()
            form.tickets[-1].ticket_id.data = ticket.id

    tickets_dict = {t.id: t for t in payment.tickets}

    for f in form.tickets:
        f._ticket = tickets_dict[f.ticket_id.data]
        f.refund.label.text = '%s - %s' % (f._ticket.id, f._ticket.type.name)
        if f._ticket.refund_id is None and f._ticket.paid:
            f._disabled = False
        else:
            f._disabled = True

    if form.validate_on_submit():
        if form.refund.data or form.stripe_refund.data:
            tickets = [f._ticket for f in form.tickets if f.refund.data and not f._disabled]
            total = sum(t.type.get_price(payment.currency) for t in tickets)

            if not total:
                flash('Please select some non-free tickets to refund')
                return redirect(url_for('.partial_refund', payment_id=payment.id))

            if any(t.user != payment.user for t in tickets):
                flash('Cannot refund transferred ticket')
                return redirect(url_for('.partial_refund', payment_id=payment.id))

            premium = payment.__class__.premium_refund(payment.currency, total)
            app.logger.info('Refunding %s tickets from payment %s, totalling %s %s and %s %s premium',
                        len(tickets), payment.id, total, payment.currency, premium, payment.currency)

            if form.stripe_refund.data:
                app.logger.info('Refunding using Stripe')
                charge = stripe.Charge.retrieve(payment.chargeid)

                if charge.refunded:
                    # This happened unexpectedly - send the email as usual
                    stripe_payment_refunded(payment)
                    flash('This charge has already been fully refunded.')
                    return redirect(url_for('.partial_refund', payment_id=payment.id))

                payment.state = 'refunding'
                refund = StripeRefund(payment, total + premium)

            else:
                app.logger.info('Refunding out of band')

                payment.state = 'refunding'
                refund = BankRefund(payment, total + premium)


            for ticket in tickets:
                ticket.paid = False
                ticket.expires = datetime.utcnow()
                ticket.refund = refund

            priced_tickets = [t for t in payment.tickets if t.type.get_price(payment.currency)]
            unpriced_tickets = [t for t in payment.tickets if not t.type.get_price(payment.currency)]

            all_refunded = False
            if all(t.refund for t in priced_tickets):
                all_refunded = True
                # Remove remaining free tickets from the payment so they're still valid.
                for ticket in unpriced_tickets:
                    if not ticket.refund:
                        app.logger.info('Removing free ticket %s from refunded payment', ticket.id)
                        if not ticket.paid:
                            # The only thing keeping this ticket from being valid was the payment
                            app.logger.info('Setting orphaned free ticket %s to paid', ticket.id)
                            ticket.paid = True

                        ticket.payment = None
                        ticket.payment_id = None

            db.session.commit()

            if form.stripe_refund.data:
                try:
                    stripe_refund = stripe.Refund.create(
                        charge=payment.chargeid,
                        amount=refund.amount_int)

                except Exception as e:
                    app.logger.warn("Exception %r refunding payment", e)
                    flash('An error occurred refunding with Stripe. Please check the state of the payment.')
                    return redirect(url_for('.partial_refund', payment_id=payment.id))

                refund.refundid = stripe_refund.id
                if stripe_refund.status != 'succeeded':
                    # Should never happen according to the docs
                    app.logger.warn("Refund status is %s, not succeeded", stripe_refund.status)
                    flash('The refund with Stripe was not successful. Please check the state of the payment.')
                    return redirect(url_for('.partial_refund', payment_id=payment.id))


            if all_refunded:
                payment.state = 'refunded'
            else:
                payment.state = 'partrefunded'

            db.session.commit()

            app.logger.info('Payment %s refund complete for a total of %s', payment.id, total + premium)
            flash('Refund for %s %s complete' % (total + premium, payment.currency))

        return redirect(url_for('.payments'))

    refunded_tickets = [t for t in payment.tickets if t.refund]
    return render_template('admin/partial-refund.html', payment=payment, form=form,
                           refunded_tickets=refunded_tickets)


class UpdateFeatureFlagForm(Form):
    # We don't allow changing feature flag names
    feature = HiddenField('Feature name', [Required()])
    enabled = BooleanField('Enabled')

class FeatureFlagForm(Form):
    flags = FieldList(FormField(UpdateFeatureFlagForm))
    new_feature = SelectField('New feature name', [Optional()],
                              choices=[('', 'Add a new flag')] + zip(DB_FEATURE_FLAGS, DB_FEATURE_FLAGS))
    new_enabled = BooleanField('New feature enabled', [Optional()])
    update = SubmitField('Update flags')


@admin.route('/feature-flags', methods=['GET', 'POST'])
@admin_required
def feature_flags():
    form = FeatureFlagForm()
    db_flags = FeatureFlag.query.all()

    if form.validate_on_submit():
        # Update existing flags
        db_flag_dict = {f.feature: f for f in db_flags}
        for flg in form.flags:
            feature = flg.feature.data

            # Update the db and clear the cache if there's a change
            if db_flag_dict[feature].enabled != flg.enabled.data:
                app.logger.info('Updating flag %s to %s', feature, flg.enabled.data)
                db_flag_dict[feature].enabled = flg.enabled.data
                db.session.commit()
                refresh_flags()

        # Add new flags if required
        if form.new_feature.data:
            new_flag = FeatureFlag(feature=form.new_feature.data,
                                   enabled=form.new_enabled.data)

            app.logger.info('Overriding new flag %s to %s', new_flag.feature, new_flag.enabled)
            db.session.add(new_flag)
            db.session.commit()
            refresh_flags()

            db_flags = FeatureFlag.query.all()

            # Unset previous form values
            form.new_feature.data = ''
            form.new_enabled.data = ''

    # Clear the list of flags (which may be stale)
    for old_field in range(len(form.flags)):
        form.flags.pop_entry()

    # Build the list of flags to display
    for flg in sorted(db_flags, key=lambda x: x.feature):
        form.flags.append_entry()
        form.flags[-1].feature.data = flg.feature
        form.flags[-1].enabled.data = flg.enabled

    return render_template('admin/feature-flags.html', form=form)


class SiteStateForm(Form):
    site_state = SelectField('Site', choices=[('', '(automatic)')] +
                             zip(VALID_STATES['site_state'], VALID_STATES['site_state']))
    sales_state = SelectField('Sales', choices=[('', '(automatic)')] +
                              zip(VALID_STATES['sales_state'], VALID_STATES['sales_state']))
    update = SubmitField('Update states')


@admin.route('/site-states', methods=['GET', 'POST'])
@admin_required
def site_states():
    form = SiteStateForm()

    db_states = SiteState.query.all()
    db_states = {s.name: s for s in db_states}

    if request.method != 'POST':
        # Empty form
        for name in VALID_STATES.keys():
            if name in db_states:
                getattr(form, name).data = db_states[name].state

    if form.validate_on_submit():
        for name in VALID_STATES.keys():
            state_form = getattr(form, name)
            if state_form.data == '':
                state_form.data = None

            if name in db_states:
                if db_states[name].state != state_form.data:
                    app.logger.info('Updating state %s to %s', name, state_form.data)
                    db_states[name].state = state_form.data

            else:
                if state_form.data:
                    state = SiteState(name, state_form.data)
                    db.session.add(state)

        db.session.commit()
        refresh_states()
        return redirect(url_for('.site_states'))

    return render_template('admin/site-states.html', form=form)

