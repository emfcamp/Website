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

from sqlalchemy import and_, or_, func, case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import join
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql import text

from decorator import decorator
import simplejson, os, re, ofxparse, sys
from decimal import Decimal
from datetime import datetime, timedelta

@app.route("/stats")
def stats():
    outstanding = Ticket.query.join(Payment).filter(
        Payment.state == 'inprogress',
        Ticket.expires >= func.now(),
        Ticket.paid == False,
    )
    paid = Ticket.query.filter(Ticket.paid == True)
    full = db.engine.execute(text("""select count(*) from ticket_type, ticket where
                                        ticket.type_id = ticket_type.id and
                                        ticket.paid = false and ticket.expires > now()
                                        and ticket_type.code LIKE 'full%'""")).scalar()

    full_bought = db.engine.execute(text("""select count(*) from ticket_type, ticket where
                                        ticket.type_id = ticket_type.id and
                                        ticket.paid = true and ticket_type.code LIKE 'full%'""")).scalar()

    kids_bought = db.engine.execute(text("""select count(*) from ticket_type, ticket where
                                        ticket.type_id = ticket_type.id and
                                        ticket.paid = true and ticket_type.code LIKE 'kids%'""")).scalar()

    confident_query = text("""
      select count(*)
      from
          ticket_type tt,
          ticket t,
          payment p
      where
          tt.id = t.type_id
          and p.id = t.payment_id
          and tt.code like :code
          and (
            p.provider = 'gocardless' and p.state = 'inprogress' and t.expires > now()
            or t.paid = true
          )
    """)

    full_confident = db.engine.execute(confident_query, code='full%').scalar()
    day_confident = db.engine.execute(confident_query, code='day%').scalar()

    full_unconfident = db.engine.execute(text("""
      select count(*)
      from
          ticket_type tt,
          ticket t,
          payment p
      where
          tt.id = t.type_id
          and p.id = t.payment_id
          and tt.code like 'full%'
          and (
            p.provider = 'banktransfer' and p.state = 'inprogress'
            or p.provider = 'googlecheckout' and p.state = 'new'
          )
          and t.expires > now()
    """)).scalar()


    stats = {
        'prepays': outstanding.filter(Ticket.type == TicketType.Prepay).count(),
        'prepays_bought_all': paid.filter(Ticket.type == TicketType.Prepay).count(),
        'full': full,
        'full_bought': full_bought,
        'kids_bought': kids_bought,
        'full_confident': full_confident,
        'full_unconfident': full_unconfident,
        'users': User.query.count(),
        'day_confident': day_confident
    }

    # A pending or purchased full ticket cancels out a purchased prepay
    user_prepays = db.session.query(
        Ticket.user_id,
        func.sum(case([
            (and_(Ticket.type == TicketType.Prepay, Ticket.paid == True), 1),
            (Ticket.type == TicketType.Full, -1),
            (Ticket.type == TicketType.FullPrepay, -1),
        ], else_=0)).label('outstanding')
    ).group_by(Ticket.user_id).subquery()

    prepays = db.session.query(func.sum(case([
        (user_prepays.c.outstanding < 0, 0)
    ], else_=user_prepays.c.outstanding))).one()

    stats['prepays_bought'] = prepays[0]

    return ' '.join('%s:%s' % i for i in stats.items())

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
                        db.session.add(t)
                        app.logger.info("ticket %s (%s, for %s) paid", t.id, t.type.name, payment.user.name)
                    payment.state = "paid"
                    db.session.add(payment)
                    db.session.commit()
                
                    # send email.
                    msg = Message("Electromagnetic Field ticket purchase update", \
                              sender=app.config.get('TICKETS_EMAIL'), \
                              recipients=[payment.user.email]
                             )
                    msg.body = render_template("tickets-paid-email-banktransfer.txt", \
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
                            app.logger.info("user %s (%s) admin: %s -> %s", user.name, user.id, user.admin, field.data)
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

class ExpireResetForm(Form):
    payment = HiddenField('payment_id', [Required()])
    reset = SubmitField('Reset')
    yes = SubmitField('Yes')
    no = SubmitField('No')

@app.route("/admin/reset-expirey", methods=['GET', 'POST'])
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
                        db.session.add(t)
                        app.logger.info("ticket %s (%s, for %s) expirey reset", t.id, t.type.name, payment.user.name)
                    db.session.commit()

                    return redirect(url_for('expire_reset'))
                elif form.no.data == True:
                    return redirect(url_for('expire_reset'))
                elif form.payment.data:
                    payment = Payment.query.get(int(form.payment.data))
                    ynform = ExpireResetForm(payment=payment.id, formdata=None)
                    return render_template('admin/admin_reset_expirey_yesno.html', ynform=ynform, payment=payment)

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
        return render_template('admin/admin_reset_expirey.html', payments=opayments, resetforms=resetforms)
    else:
        return(('', 404))
