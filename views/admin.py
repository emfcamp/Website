from main import app, db, gocardless, mail
from models.user import User
from models.payment import Payment, BankPayment, GoCardlessPayment
from models.ticket import TicketType, Ticket

from flask import \
    render_template, redirect, request, flash, \
    url_for, abort, send_from_directory, session
from flaskext.login import \
    login_user, login_required, logout_user, current_user
from flaskext.mail import Message
from flaskext.wtf import \
    Form, Required, Email, EqualTo, ValidationError, \
    TextField, PasswordField, SelectField, HiddenField, \
    SubmitField, BooleanField, IntegerField, HiddenInput, \
    DecimalField

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import text

from decorator import decorator
import simplejson, os, re
from datetime import datetime, timedelta

@app.route("/stats")
def stats():
    ret = {}
    conn = db.session.connection()
    result = conn.execute(text("""SELECT count(t.id) as tickets from payment p, ticket t, ticket_type tt where
                                p.state='inprogress' and t.payment_id = p.id and t.expires >= date('now') and
                                t.type_id = tt.id and tt.name = 'Prepay Camp Ticket'""")).fetchall()
    ret["prepays"] = result[0][0]
    ret["users"] = User.query.count()
    ret["prepays_bought"] = TicketType.Prepay.query.filter(Ticket.paid == True).count()

    return ' '.join('%s:%s' % i for i in ret.items())

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
                    app.logger.info("%s Manually reconciled payment %d (%s)", current_user.name, payment.id, payment.bankref)
                    for t in payment.tickets:
                        t.paid = True
                        db.session.add(t)
                        app.logger.info("ticket %d (%s, for %s) paid", t.id, t.type.name, payment.user.name)
                    payment.state = "paid"
                    db.session.add(payment)
                    db.session.commit()
                
                    # send email.
                    msg = Message("Electromagnetic Field ticket purchase update", \
                              sender=app.config.get('TICKETS_EMAIL'), \
                              recipients=[payment.user.email]
                             )
                    msg.body = render_template("tickets-paid-email-banktransfer.txt", \
                              basket={"count" : len(payment.tickets.all()), "reference" : payment.bankref}, \
                              user = payment.user, payment=payment
                             )
                    mail.send(msg)
                
                    flash("Payment ID %d now marked as paid" % (payment.id))
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
    # TODO : paginate?

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
                            app.logger.info("user %s (%d) admin: %s -> %s" % (user.name, user.id, user.admin, field.data))
                            user.admin = field.data
                            db.session.add(user)
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
    cost = DecimalField('Cost', [Required()])

@app.route("/admin/ticket-types", methods=['GET', 'POST'])
@login_required
def ticket_types():
    if current_user.admin:
        form = None
        if request.method == 'POST':
            form = NewTicketTypeForm()
            if form.validate():
                tt = TicketType(form.name.data, form.capacity.data, form.limit.data, form.cost.data)
                db.session.add(tt)
                db.session.commit()
                return redirect(url_for('ticket_types'))

        types = TicketType.query.all()
        if not form:
            form = NewTicketTypeForm(formdata=None)
        return render_template('admin/admin_ticket_types.html', types=types, form=form)
    else:
        return(('', 404))
