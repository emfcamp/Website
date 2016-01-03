from datetime import datetime, timedelta
from functools import wraps

from Levenshtein import ratio, jaro
from flask import (
    render_template, redirect, request, flash,
    url_for, abort, current_app as app, Blueprint
)
from flask.ext.login import login_required, current_user
from flask_mail import Message
from wtforms.validators import Optional, Regexp, Required
from wtforms.widgets import TextArea
from wtforms import (
    SubmitField, BooleanField, StringField, RadioField, HiddenField,
    DateField, IntegerField, FieldList, FormField, SelectField,
)
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.functions import func

from main import db, mail, cache
from models.user import User
from models.payment import Payment, BankPayment, BankTransaction, StateException
from models.ticket import (
    Ticket, TicketCheckin, TicketType, TicketPrice, TicketTransfer
)
from models.cfp import Proposal
from models.feature_flag import FeatureFlag, DB_FEATURE_FLAGS
from .common import feature_enabled
from .common.forms import Form
from .payments.stripe import (
    StripeUpdateUnexpected, StripeUpdateConflict, stripe_update_payment,
)

admin = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if current_user.is_authenticated():
            if current_user.admin:
                return f(*args, **kwargs)
            abort(404)
        return app.login_manager.unauthorized()
    return wrapped


@admin.context_processor
def admin_counts():
    if not request.path.startswith('/admin'):
        return {}

    unreconciled_count = BankTransaction.query.filter_by(payment_id=None, suppressed=False).count()

    expiring_count = BankPayment.query.join(Ticket).filter(
        BankPayment.state == 'inprogress',
        Ticket.expires < datetime.utcnow() + timedelta(days=3),
    ).group_by(BankPayment.id).count()

    return {'unreconciled_count': unreconciled_count,
            'expiring_count': expiring_count}


@admin.route("/stats")
def stats():
    full = Ticket.query.join(TicketType).filter_by(admits='full').join(Payment).filter(Payment.state != 'new')
    kids = Ticket.query.join(TicketType).filter_by(admits='kid').join(Payment).filter(Payment.state != 'new')

    # cancelled tickets get their expiry set to the cancellation time
    full_unexpired = full.filter(Ticket.expires >= datetime.utcnow())
    kids_unexpired = kids.filter(Ticket.expires >= datetime.utcnow())
    full_unpaid = full_unexpired.filter(Ticket.paid == False)  # noqa
    kids_unpaid = kids_unexpired.filter(Ticket.paid == False)  # noqa

    full_bought = full.filter(Ticket.paid)
    kids_bought = kids.filter(Ticket.paid)

    full_gocardless_unpaid = full_unpaid.filter(Payment.provider == 'gocardless',
                                                Payment.state == 'inprogress')
    full_banktransfer_unpaid = full_unpaid.filter(Payment.provider == 'banktransfer',
                                                  Payment.state == 'inprogress')

    parking_bought = Ticket.query.filter_by(paid=True).join(TicketType).filter(
        TicketType.admits == 'car')
    campervan_bought = Ticket.query.filter_by(paid=True).join(TicketType).filter(
        TicketType.admits == 'campervan')

    checked_in = Ticket.query.filter(TicketType.admits.in_(['full', 'kid'])) \
                             .join(TicketCheckin).filter_by(checked_in=True)
    badged_up = TicketCheckin.query.filter_by(badged_up=True)

    users = User.query

    proposals = Proposal.query

    queries = [
        'full', 'kids',
        'full_bought', 'kids_bought',
        'full_unpaid', 'kids_unpaid',
        'full_gocardless_unpaid', 'full_banktransfer_unpaid',
        'parking_bought', 'campervan_bought',
        'checked_in', 'badged_up',
        'users',
        'proposals',
    ]

    stats = ['%s:%s' % (q, locals()[q].count()) for q in queries]
    return ' '.join(stats)


@admin.route('/')
@admin_required
def home():
    return render_template('admin/admin.html')


@admin.route('/transactions')
@admin_required
def transactions():
    txns = BankTransaction.query.filter_by(payment_id=None, suppressed=False).order_by('posted desc')
    return render_template('admin/txns.html', txns=txns)


class TransactionSuppressForm(Form):
    suppress = SubmitField("Suppress")


@admin.route('/transaction/<int:txn_id>/suppress', methods=['GET', 'POST'])
@admin_required
def transaction_suppress(txn_id):
    try:
        txn = BankTransaction.query.get(txn_id)
    except NoResultFound:
        abort(404)

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


@admin.route('/ticket-types', methods=['GET', 'POST'])
@admin_required
def ticket_types():
    ticket_types = TicketType.query.all()
    totals = {}
    for tt in ticket_types:
        sold = tt.get_sold()
        totals[tt.admits] = totals[tt.admits] + sold if tt.admits in totals else sold
    return render_template('admin/ticket-types.html', ticket_types=ticket_types, totals=totals)


class EditTicketTypeForm(Form):
    name = StringField('Name')
    order = IntegerField('Order')
    type_limit = IntegerField('Maximum tickets to sell')
    personal_limit = IntegerField('Maximum tickets to sell to an individual')
    expires = DateField('Expiry Date (Optional)', [Optional()])
    description = StringField('Description', [Optional()], widget=TextArea())
    submit = SubmitField('Save')

    def init_with_ticket_type(self, ticket_type):
        self.name.data = ticket_type.name
        self.order.data = ticket_type.order
        self.type_limit.data = ticket_type.type_limit
        self.personal_limit.data = ticket_type.personal_limit
        self.expires.data = ticket_type.expires
        self.description.data = ticket_type.description


@admin.route('/ticket-types/<int:type_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_ticket_type(type_id):
    form = EditTicketTypeForm()

    ticket_type = TicketType.query.get(type_id)
    if form.validate_on_submit():
        for attr in ['name', 'order', 'type_limit', 'personal_limit', 'expires', 'description']:
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
    admits = RadioField('Admits', choices=[('full', 'Adult'), ('kid', 'Under 16'),
                                           ('campervan', 'Campervan'), ('car', 'Car'),
                                           ('other', 'Other')])
    type_limit = IntegerField('Maximum tickets to sell')
    personal_limit = IntegerField('Maximum tickets to sell to an individual')
    expires = DateField('Expiry Date (Optional)', [Optional()])
    price_gbp = IntegerField('Price (GBP)')
    price_eur = IntegerField('Price (EUR)')
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
        new_id = TicketType.query.all()[-1].id + 1

        expires = form.expires.data if form.expires.data else None
        token = form.discount_token.data if form.discount_token.data else None
        description = form.description.data if form.description.data else None

        tt = TicketType(new_id, form.order.data, form.admits.data,
                        form.name.data, form.type_limit.data, expires=expires,
                        discount_token=token, description=description,
                        personal_limit=form.personal_limit.data,
                        has_badge=form.has_badge.data,
                        is_transferable=form.is_transferable.data)

        tt.prices = [TicketPrice('GBP', form.price_gbp.data),
                     TicketPrice('EUR', form.price_eur.data)]
        app.logger.info('Adding new TicketType %s', tt)
        db.session.add(tt)
        db.session.commit()
        return redirect(url_for('.ticket_type_details', type_id=new_id))

    if copy_id != -1:
        form.init_with_ticket_type(TicketType.query.get(copy_id))

    return render_template('admin/new-ticket-type.html', ticket_type_id=copy_id, form=form)


@admin.route('/ticket-types/<int:type_id>')
@admin_required
def ticket_type_details(type_id):
    ticket_type = TicketType.query.get(type_id)
    return render_template('admin/ticket-type-details.html', ticket_type=ticket_type)

@admin.route('/transfers')
@admin_required
def ticket_transfers():
    transfer_logs = TicketTransfer.query.all()
    return render_template('admin/ticket-transfers.html', transfers=transfer_logs)


@admin.route("/admin/make-admin", methods=['GET', 'POST'])
@login_required
def make_admin():
    if current_user.admin:

        class MakeAdminForm(Form):
            change = SubmitField('Change')

        users = User.query.order_by(User.id).all()
        # The list of users can change between the
        # form being generated and it being submitted, but the id's should remain stable
        for u in users:
            setattr(MakeAdminForm, str(u.id) + "_admin", BooleanField('admin', default=u.admin))

        if request.method == 'POST':
            form = MakeAdminForm()
            if form.validate():
                for field in form:
                    if field.name.endswith('_admin'):
                        id = int(field.name.split("_")[0])
                        user = User.query.get(id)
                        if user.admin != field.data:
                            app.logger.info("user %s (%s) admin: %s -> %s", user.name,
                                            user.id, user.admin, field.data)
                            user.admin = field.data
                            db.session.commit()
                return redirect(url_for('.make_admin'))
        adminform = MakeAdminForm(formdata=None)
        return render_template('admin/users-make-admin.html', users=users, adminform=adminform)
    else:
        return(('', 404))


@admin.route("/admin/make-arrivals", methods=['GET', 'POST'])
@login_required
def make_arrivals():
    if current_user.arrivals:

        class MakeArrivalsForm(Form):
            change = SubmitField('Change')

        users = User.query.order_by(User.id).all()
        # The list of users can change between the
        # form being generated and it being submitted, but the id's should remain stable
        for u in users:
            setattr(MakeArrivalsForm, str(u.id) + "_arrivals", BooleanField('arrivals', default=u.arrivals))

        if request.method == 'POST':
            form = MakeArrivalsForm()
            if form.validate():
                for field in form:
                    if field.name.endswith('_arrivals'):
                        id = int(field.name.split("_")[0])
                        user = User.query.get(id)
                        if user.arrivals != field.data:
                            app.logger.info("user %s (%s) arrivals: %s -> %s", user.name,
                                            user.id, user.arrivals, field.data)
                            user.arrivals = field.data
                            db.session.commit()
                return redirect(url_for('.make_arrivals'))
        arrivalsform = MakeArrivalsForm(formdata=None)
        return render_template('admin/users-make-arrivals.html', users=users, arrivalsform=arrivalsform)
    else:
        return(('', 404))


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
                cache.delete_memoized(feature_enabled, feature)

        # Add new flags if required
        if form.new_feature.data:
            new_flag = FeatureFlag(feature=form.new_feature.data,
                                   enabled=form.new_enabled.data)

            app.logger.info('Overriding new flag %s to %s', new_flag.feature, new_flag.enabled)
            db.session.add(new_flag)
            db.session.commit()

            # Clear the cache for which would have previously returned None
            cache.delete_memoized(feature_enabled, new_flag.feature)

            db_flags = FeatureFlag.query.all()

            # Unset previous form values
            form.new_feature.data = ''
            form.new_enabled.data = ''

    # Clear the list of flags (which may be stale)
    for old_field in range(len(form.flags)):
        form.flags.pop_entry()

    # Build the list of flags to display
    for flg in db_flags:
        form.flags.append_entry()
        form.flags[-1].feature.data = flg.feature
        form.flags[-1].enabled.data = flg.enabled

    return render_template('admin/feature-flags.html', form=form)
