# flake8: noqa (there are a load of errors here we need to fix)
from main import app, db, mail
from models.user import User
from models.payment import Payment, BankPayment, BankTransaction
from models.ticket import TicketType, Ticket
from models.cfp import Proposal
from views import Form, HiddenIntegerField

from flask import (
    render_template, redirect, request, flash,
    url_for, abort,
)
from flask.ext.login import login_required, current_user
from flaskext.mail import Message

from wtforms.validators import Required
from wtforms import (
    TextField, HiddenField,
    SubmitField, BooleanField, IntegerField, DecimalField,
)

from sqlalchemy.orm.exc import NoResultFound

from Levenshtein import ratio, jaro

from datetime import datetime, timedelta
from functools import wraps

def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if current_user.is_authenticated() and current_user.admin:
            return f(*args, **kwargs)
        return app.login_manager.unauthorized()
    return wrapped


@app.route("/stats")
def stats():
    full = Ticket.query.filter( Ticket.code.startswith('full') )
    kids = Ticket.query.filter( Ticket.code.startswith('kids') )

    full_unpaid = full.filter( Ticket.expires >= datetime.utcnow(), Ticket.paid == False )
    kids_unpaid = kids.filter( Ticket.expires >= datetime.utcnow(), Ticket.paid == False )

    full_bought = full.filter( Ticket.paid == True )
    kids_bought = kids.filter( Ticket.paid == True )

    full_gocardless_unpaid = full_unpaid.join(Payment).filter(Payment.provider == 'gocardless', Payment.state == 'inprogress')
    full_banktransfer_unpaid = full_unpaid.join(Payment).filter(Payment.provider == 'banktransfer', Payment.state == 'inprogress')

    users = User.query

    proposals = Proposal.query

    queries = [
        'full', 'kids',
        'full_bought', 'kids_bought',
        'full_unpaid', 'kids_unpaid',
        'full_gocardless_unpaid', 'full_banktransfer_unpaid',
        'users',
        'proposals',
    ]

    stats = ['%s:%s' % (q, locals()[q].count()) for q in queries]
    return ' '.join(stats)

@app.route('/admin')
@admin_required
def admin():
    unreconciled_count = BankTransaction.query.filter_by(payment_id=None, suppressed=False).count()
    return render_template('admin/admin.html',
                           unreconciled_count=unreconciled_count)


class TransactionSuppressForm(Form):
    suppress = SubmitField("Suppress")

@app.route('/admin/transactions')
@admin_required
def admin_txns():
    txns = BankTransaction.query.filter_by(payment_id=None, suppressed=False)
    suppress_form = TransactionSuppressForm(formdata=None)
    return render_template('admin/txns.html', txns=txns, suppress_form=suppress_form)

@app.route('/admin/transaction/<int:txn_id>/suppress', methods=['POST'])
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
            app.logger.info('Transaction suppressed')
            db.session.commit()

    return redirect(url_for('admin_txns'))

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

    # check date against expiry?

    app.logger.debug('Scores for txn %s payment %s: %s %s %s',
                     txn.id, payment.id, bankref_score, name_score, other_score)
    return bankref_score + name_score + other_score

class ManualReconcileForm(Form):
    payment_id = HiddenIntegerField("Payment ID")
    reconcile = SubmitField("Reconcile")

@app.route('/admin/transaction/<int:txn_id>/reconcile', methods=['GET', 'POST'])
@admin_required
def admin_txn_reconcile(txn_id):
    try:
        txn = BankTransaction.query.get(txn_id)
    except NoResultFound:
        abort(404)

    form = ManualReconcileForm()
    if form.validate_on_submit():
        app.logger.info('Processing transaction %s (%s)', txn.id, txn.payee)

        if form.reconcile.data:
            payment = BankPayment.query.get(form.payment_id.data)
            app.logger.info("%s manually reconciling against payment %s (%s) by %s",
                            current_user.name, payment.id, payment.bankref, payment.user.email)

            if txn.payment:
                app.logger.error("Transaction already reconciled")
                return redirect(url_for('admin_txns'))

            if payment.state == 'paid':
                app.logger.error("Payment has already been paid")
                return redirect(url_for('admin_txns'))

            txn.payment = payment
            for t in payment.tickets:
                t.paid = True
            payment.state = 'paid'
            db.session.commit()

            msg = Message("Electromagnetic Field ticket purchase update",
                          sender=app.config['TICKETS_EMAIL'],
                          recipients=[payment.user.email])
            msg.body = render_template("tickets-paid-email-banktransfer.txt",
                          user=payment.user, payment=payment)
            mail.send(msg)

            flash("Payment ID %s marked as paid" % payment.id)
            return redirect(url_for('admin_txns'))

    payments = BankPayment.query.filter_by(state='inprogress').order_by(BankPayment.bankref).all()
    scores = [score_reconciliation(txn, p) for p in payments]
    scores_payments = reversed(sorted(zip(scores, payments))[:20])

    suppress_form = TransactionSuppressForm(formdata=None)
    payments_forms = []
    for score, payment in scores_payments:
        form = ManualReconcileForm(payment_id=payment.id, formdata=None)
        payments_forms.append((payment, form))

    app.logger.info('Proposing %s payments ')
    return render_template('admin/txn_reconcile.html', txn=txn, payments_forms=payments_forms,
                           suppress_form=suppress_form)

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
        return render_template('admin/admin_make_admin.html', users=users, adminform = adminform)
    else:
        return(('', 404))

class NewTicketTypeForm(Form):
    name = TextField('Name', [Required()])
    capacity = IntegerField('Capacity', [Required()])
    limit = IntegerField('Limit', [Required()])
    price_gbp = DecimalField('Price in GBP', [Required()])
    price_eur = DecimalField('Price in EUR', [Required()])

@app.route("/admin/ticket-types", methods=['GET', 'POST'])
@login_required
def ticket_types():
    if current_user.admin:
        form = None
        if request.method == 'POST':
            form = NewTicketTypeForm()
            if form.validate():
                tt = TicketType(form.name.data, form.capacity.data, form.limit.data)
                tt.prices = [TicketPrice('GBP', form.price_gbp), TicketPrice('EUR', form.price_eur)]
                db.session.add(tt)
                db.session.commit()
                return redirect(url_for('ticket_types'))

        types = TicketType.query.all()
        if not form:
            form = NewTicketTypeForm(formdata=None)
        return render_template('admin/admin_ticket_types.html', types=types, form=form)
    else:
        return(('', 404))

class ExpireResetForm(Form):
    payment = HiddenField('payment_id', [Required()])
    reset = SubmitField('Reset')
    yes = SubmitField('Yes')
    no = SubmitField('No')

@app.route("/admin/reset-expiry", methods=['GET', 'POST'])
@login_required
def expire_reset():
    if current_user.admin:
        if request.method == "POST":
            form = ExpireResetForm()
            if form.validate():
                if form.yes.data == True:
                    payment = Payment.query.get(int(form.payment.data))
                    app.logger.info("%s Manually reset expiry for tickets for payment %s", current_user.name, payment.id)
                    for t in payment.tickets:
                        t.expires = datetime.utcnow() + timedelta(10)
                        app.logger.info("ticket %s (%s, for %s) expiry reset", t.id, t.type.name, payment.user.name)
                    db.session.commit()

                    return redirect(url_for('expire_reset'))
                elif form.no.data == True:
                    return redirect(url_for('expire_reset'))
                elif form.payment.data:
                    payment = Payment.query.get(int(form.payment.data))
                    ynform = ExpireResetForm(payment=payment.id, formdata=None)
                    return render_template('admin/admin_reset_expiry_yesno.html', ynform=ynform, payment=payment)

        # >= datetime.utcnow()(Ticket.expires >= datetime.utcnow()
        unpaid = Ticket.query.filter(Ticket.paid == False).order_by(Ticket.expires).all()
        payments = {}
        for t in unpaid:
            if t.payment != None:
                if t.payment.id not in payments:
                    payments[t.payment.id] = t.payment
        resetforms = {}
        opayments = []
        for p in payments:
            resetforms[p] = ExpireResetForm(payment=p, formdata=None)
            opayments.append(payments[p])
        return render_template('admin/admin_reset_expiry.html', payments=opayments, resetforms=resetforms)
    else:
        return(('', 404))

@app.route('/admin/receipt/<receipt>')
@login_required
def admin_receipt(receipt):
    if not current_user.admin:
        return ('', 404)

    try:
        user = User.query.filter_by(receipt=receipt).one()
        tickets = list(user.tickets)
    except NoResultFound, e:
        try:
            ticket = Ticket.query.filter_by(receipt=receipt).one()
            tickets = [ticket]
            user = ticket.user
        except NoResultFound, e:
            raise ValueError('Cannot find receipt')

    return render_template('admin/admin_receipt.htm', user=user, tickets=tickets)
