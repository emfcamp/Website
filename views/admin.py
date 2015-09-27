from main import app, db, mail
from models.user import User
from models.payment import Payment, BankPayment, BankTransaction
from models.ticket import Ticket, TicketCheckin, TicketType, TicketPrice
from models.cfp import Proposal
from views import Form
from views.payment.stripe import (
    StripeUpdateUnexpected, StripeUpdateConflict, stripe_update_payment,
)

from flask import (
    render_template, redirect, request, flash,
    url_for, abort,
)
from flask.ext.login import login_required, current_user
from flask_mail import Message

from wtforms.validators import Optional, Regexp
from wtforms.widgets import TextArea
from wtforms import (
    SubmitField, BooleanField, TextField, RadioField, DateField, IntegerField
)

from sqlalchemy import or_
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.functions import func

from Levenshtein import ratio, jaro

from datetime import datetime, timedelta
from functools import wraps

def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if current_user.is_authenticated():
            if current_user.admin:
                return f(*args, **kwargs)
            abort(404)
        return app.login_manager.unauthorized()
    return wrapped

@app.context_processor
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


@app.route("/stats")
def stats():
    full = Ticket.query.join(Payment).filter( Ticket.code.startswith('full'), Payment.state != 'new' )
    kids = Ticket.query.join(Payment).filter( Ticket.code.startswith('kids'), Payment.state != 'new' )

    # cancelled tickets get their expiry set to the cancellation time
    full_unexpired = full.filter( Ticket.expires >= datetime.utcnow() )
    kids_unexpired = kids.filter( Ticket.expires >= datetime.utcnow() )
    full_unpaid = full_unexpired.filter( Ticket.paid == False) # noqa
    kids_unpaid = kids_unexpired.filter( Ticket.paid == False) # noqa

    full_bought = full.filter(Ticket.paid)
    kids_bought = kids.filter(Ticket.paid)

    full_gocardless_unpaid = full_unpaid.filter(Payment.provider == 'gocardless', Payment.state == 'inprogress')
    full_banktransfer_unpaid = full_unpaid.filter(Payment.provider == 'banktransfer', Payment.state == 'inprogress')

    parking_bought = Ticket.query.filter_by(paid=True, code='parking')
    campervan_bought = Ticket.query.filter_by(paid=True, code='campervan')

    checked_in = Ticket.query.filter( or_(Ticket.code.startswith('full'), Ticket.code.startswith('kids')) ) \
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

@app.route('/admin')
@admin_required
def admin():
    return render_template('admin/admin.html')


@app.route('/admin/transactions')
@admin_required
def admin_txns():
    txns = BankTransaction.query.filter_by(payment_id=None, suppressed=False).order_by('posted desc')
    return render_template('admin/txns.html', txns=txns)

class TransactionSuppressForm(Form):
    suppress = SubmitField("Suppress")

@app.route('/admin/transaction/<int:txn_id>/suppress', methods=['GET', 'POST'])
@admin_required
def admin_txn_suppress(txn_id):
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
            return redirect(url_for('admin_txns'))

    return render_template('admin/txn-suppress.html', txn=txn, form=form)

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


@app.route('/admin/transaction/<int:txn_id>/reconcile')
@admin_required
def admin_txn_suggest_payments(txn_id):
    txn = BankTransaction.query.get_or_404(txn_id)

    payments = BankPayment.query.filter_by(state='inprogress').order_by(BankPayment.bankref).all()
    payments = sorted(payments, key=lambda p: score_reconciliation(txn, p))
    payments = list(reversed(payments[-20:]))

    app.logger.info('Suggesting %s payments for txn %s', len(payments), txn.id)
    return render_template('admin/txn-suggest-payments.html', txn=txn, payments=payments)


class ManualReconcilePaymentForm(Form):
    reconcile = SubmitField("Reconcile")

@app.route('/admin/transaction/<int:txn_id>/reconcile/<int:payment_id>', methods=['GET', 'POST'])
@admin_required
def admin_txn_reconcile(txn_id, payment_id):
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
                return redirect(url_for('admin_txns'))

            if payment.state == 'paid':
                app.logger.error("Payment has already been paid")
                flash("Payment %s already paid" % payment.id)
                return redirect(url_for('admin_txns'))

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
            return redirect(url_for('admin_txns'))

    return render_template('admin/txn-reconcile.html', txn=txn, payment=payment, form=form)

@app.route('/admin/ticket-types', methods=['GET', 'POST'])
@admin_required
def ticket_types():
    ticket_types = TicketType.query.all()
    return render_template('admin/ticket-types.html', ticket_types=ticket_types)

@app.route('/admin/ticket-types/<int:type_id>')
@admin_required
def ticket_type_details(type_id):
    ticket_type = TicketType.query.get(type_id)
    return render_template('admin/ticket-type-details.html', ticket_type=ticket_type)

class TicketTypeForm(Form):
    name = TextField('Name')
    order = IntegerField('Order')
    admits = RadioField('Admits', choices=[('full', 'Adult'), ('kid', 'Under 16'),
        ('campervan', 'Campervan'), ('car', 'Car'), ('other', 'Other')])
    type_limit = IntegerField('Maximum tickets to sell')
    personal_limit = IntegerField('Maximum tickets to sell to an individual')
    expires = DateField('Expiry Date (Optional)', [Optional()])
    price_gbp = IntegerField('Price (GBP)')
    price_eur = IntegerField('Price (EUR)')
    discount_token = TextField('Discount token', [Optional(), Regexp('^[-_0-9a-zA-Z]+$')])
    description = TextField('Description', [Optional()], widget=TextArea())
    submit = SubmitField('Add')

@app.route('/admin/new-ticket-type/', defaults={'copy_id': -1}, methods=['GET', 'POST'])
@app.route('/admin/new-ticket-type/<int:copy_id>', methods=['GET', 'POST'])
@admin_required
def new_ticket_type(copy_id):
    form = TicketTypeForm()

    if form.validate_on_submit():
        new_id = TicketType.query.all()[-1].id + 1

        expires = form.expires.data if form.expires.data else None
        token = form.discount_token.data if form.discount_token.data else None
        description = form.description.data if form.description.data else None

        tt = TicketType(new_id, form.order.data, form.admits.data, 
            form.name.data, form.type_limit.data, expires=expires,
            discount_token=token, description=description,
            personal_limit=form.personal_limit.data)

        tt.prices = [TicketPrice('GBP', form.price_gbp.data), 
                     TicketPrice('EUR', form.price_eur.data)]
        db.session.add(tt)
        db.session.commit()
        return redirect(url_for('ticket_type_details', type_id=new_id))

    if copy_id != -1:
        copy_type = TicketType.query.get(copy_id)
        form.name.data = copy_type.name
        form.order.data = copy_type.order
        form.admits.data = copy_type.admits
        form.type_limit.data = copy_type.type_limit
        form.personal_limit.data = copy_type.personal_limit
        form.expires.data = copy_type.expires
        form.price_gbp.data = copy_type.get_price('GBP')
        form.price_eur.data = copy_type.get_price('EUR')
        form.description.data = copy_type.description
        form.discount_token.data = copy_type.discount_token

    return render_template('admin/new-ticket-type.html', form=form)


@app.route("/admin/make-admin", methods=['GET', 'POST'])
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
                            app.logger.info("user %s (%s) admin: %s -> %s", user.name, user.id, user.admin, field.data)
                            user.admin = field.data
                            db.session.commit()
                return redirect(url_for('make_admin'))
        adminform = MakeAdminForm(formdata=None)
        return render_template('admin/users-make-admin.html', users=users, adminform=adminform)
    else:
        return(('', 404))

@app.route("/admin/make-arrivals", methods=['GET', 'POST'])
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
                            app.logger.info("user %s (%s) arrivals: %s -> %s", user.name, user.id, user.arrivals, field.data)
                            user.arrivals = field.data
                            db.session.commit()
                return redirect(url_for('make_arrivals'))
        arrivalsform = MakeArrivalsForm(formdata=None)
        return render_template('admin/users-make-arrivals.html', users=users, arrivalsform=arrivalsform)
    else:
        return(('', 404))


@app.route('/admin/payments')
@admin_required
def admin_payments():
    payments = Payment.query.join(Ticket).with_entities(
        Payment,
        func.min(Ticket.expires).label('first_expires'),
        func.count(Ticket.id).label('ticket_count'),
    ).group_by(Payment).order_by(Payment.id).all()

    return render_template('admin/payments.html', payments=payments)

@app.route('/admin/payments/expiring')
@admin_required
def admin_expiring():
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

@app.route('/admin/payment/<int:payment_id>/reset-expiry', methods=['GET', 'POST'])
@admin_required
def admin_reset_expiry(payment_id):
    payment = BankPayment.query.get_or_404(payment_id)

    form = ResetExpiryForm()
    if form.validate_on_submit():
        if form.reset.data:
            app.logger.info("%s manually extending expiry for payment %s", current_user.name, payment.id)
            for t in payment.tickets:
                if payment.currency == 'GBP':
                    t.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS_TRANSFER'))
                elif payment.currency == 'EUR':
                    t.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS_TRANSFER_EURO'))
                app.logger.info("Reset expiry for ticket %s", t.id)

            db.session.commit()

            flash("Expiry reset for payment %s" % payment.id)
            return redirect(url_for('admin_expiring'))

    return render_template('admin/payment-reset-expiry.html', payment=payment, form=form)

class SendReminderForm(Form):
    remind = SubmitField("Send reminder")

@app.route('/admin/payment/<int:payment_id>/reminder', methods=['GET', 'POST'])
@admin_required
def admin_send_reminder(payment_id):
    payment = BankPayment.query.get_or_404(payment_id)

    form = SendReminderForm()
    if form.validate_on_submit():
        if form.remind.data:
            app.logger.info("%s sending reminder email to %s <%s> for payment %s",
                            current_user.name, payment.user.name, payment.user.email, payment.id)

            if payment.reminder_sent:
                app.logger.error('Reminder for payment %s already sent', payment.id)
                flash("Cannot send duplicate reminder email for payment %s" % payment.id)
                return redirect(url_for('admin_expiring'))

            msg = Message("Electromagnetic Field ticket purchase update",
                          sender=app.config['TICKETS_EMAIL'],
                          recipients=[payment.user.email])
            msg.body = render_template("emails/tickets-reminder.txt", payment=payment)
            mail.send(msg)

            payment.reminder_sent = True
            db.session.commit()

            flash("Reminder email for payment %s sent" % payment.id)
            return redirect(url_for('admin_expiring'))

    return render_template('admin/payment-send-reminder.html', payment=payment, form=form)


class UpdatePaymentForm(Form):
    update = SubmitField("Update payment")

@app.route('/admin/payment/<int:payment_id>/update', methods=['GET', 'POST'])
@admin_required
def admin_update_payment(payment_id):
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
                return redirect(url_for('admin_update_payment', payment_id=payment.id))
            except StripeUpdateUnexpected:
                flash('Unable to update due to an unexpected response from Stripe')
                return redirect(url_for('admin_update_payment', payment_id=payment.id))

            flash('Payment status updated')
            return redirect(url_for('admin_update_payment', payment_id=payment.id))

    return render_template('admin/payment-update.html', payment=payment, form=form)


class CancelPaymentForm(Form):
    cancel = SubmitField("Cancel payment")

@app.route('/admin/payment/<int:payment_id>/cancel', methods=['GET', 'POST'])
@admin_required
def admin_cancel_payment(payment_id):
    payment = BankPayment.query.get_or_404(payment_id)

    form = CancelPaymentForm()
    if form.validate_on_submit():
        if form.cancel.data:
            app.logger.info("%s manually cancelling payment %s", current_user.name, payment.id)
            payment.cancel()
            db.session.commit()

            flash("Payment %s cancelled" % payment.id)
            return redirect(url_for('admin_expiring'))

    return render_template('admin/payment-cancel.html', payment=payment, form=form)

