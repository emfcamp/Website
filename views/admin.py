# flake8: noqa (there are a load of errors here we need to fix)
from main import app, db, mail
from models.user import User
from models.payment import Payment, BankPayment
from models.ticket import TicketType, Ticket
from models.cfp import Proposal
from views import Form

from flask import (
    render_template, redirect, request, flash,
    url_for,
)
from flask.ext.login import login_required, current_user
from flaskext.mail import Message

from wtforms.validators import Required
from wtforms import (
    TextField, HiddenField,
    SubmitField, BooleanField, IntegerField, DecimalField,
)

from sqlalchemy.orm.exc import NoResultFound

from datetime import datetime, timedelta

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

@app.route("/admin")
@login_required
def admin():
    if current_user.admin:
        return render_template('admin/admin.html')
    else:
        return(('', 404))

class ManualReconcileForm(Form):
    payment = HiddenField('payment_id', [Required()])
    reconcile = SubmitField('Reconcile')
    yes = SubmitField('Yes')
    no = SubmitField('No')

@app.route("/admin/manual-reconcile", methods=['GET', 'POST'])
@login_required
def manual_reconcile():
    if current_user.admin:
        if request.method == "POST":
            form = ManualReconcileForm()
            if form.validate():
                if form.yes.data == True:
                    payment = BankPayment.query.get(int(form.payment.data))
                    app.logger.info("%s Manually reconciled payment %s (%s)", current_user.name, payment.id, payment.bankref)
                    for t in payment.tickets:
                        t.paid = True
                        app.logger.info("ticket %s (%s, for %s) paid", t.id, t.type.name, payment.user.name)
                    payment.state = "paid"
                    db.session.commit()
                
                    msg = Message("Electromagnetic Field ticket purchase update",
                              sender=app.config['TICKETS_EMAIL'],
                              recipients=[payment.user.email]
                             )
                    msg.body = render_template("tickets-paid-email-banktransfer.txt",
                              user = payment.user, payment=payment
                             )
                    mail.send(msg)
                
                    flash("Payment ID %s now marked as paid" % (payment.id))
                    return redirect(url_for('manual_reconcile'))
                elif form.no.data == True:
                    return redirect(url_for('manual_reconcile'))
                elif form.reconcile.data == True:
                    payment = BankPayment.query.get(int(form.payment.data))
                    ynform = ManualReconcileForm(payment=payment.id, formdata=None)
                    return render_template('admin/admin_manual_reconcile_yesno.html', ynform=ynform, payment=payment)

        payments = BankPayment.query.filter(BankPayment.state == "inprogress").order_by(BankPayment.bankref).all()
        paymentforms = {}
        for p in payments:
            paymentforms[p.id] = ManualReconcileForm(payment=p.id, formdata=None)
        return render_template('admin/admin_manual_reconcile.html', payments=payments, paymentforms=paymentforms)
    else:
        return(('', 404))

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
