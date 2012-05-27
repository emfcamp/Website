from main import app, db, gocardless, mail
from models.user import User, PasswordReset
from models.payment import Payment
from models.ticket import TicketType, Ticket
from flask import render_template, redirect, request, flash, url_for, abort, send_from_directory, session
from flaskext.login import login_user, login_required, logout_user, current_user
from flaskext.mail import Message
from flaskext.wtf import \
    Form, Required, Email, EqualTo, ValidationError, \
    TextField, PasswordField, SelectField
from sqlalchemy.exc import IntegrityError
from decorator import decorator
import simplejson, os

def feature_flag(flag):
    def call(f, *args, **kw):
        if app.config.get(flag, False) == True:
            return f(*args, **kw)
        return abort(404)
    return decorator(call)

class IntegerSelectField(SelectField):
    def __init__(self, *args, **kwargs):
        kwargs['coerce'] = int
        fmt = kwargs.pop('fmt', str)
        min = kwargs.pop('min', 1)
        max = kwargs.pop('max')
        kwargs['choices'] = [(i, fmt(i)) for i in range(min, max + 1)]
        SelectField.__init__(self, *args, **kwargs)


@app.route("/")
def main():
    return render_template('main.html')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static/images'),
                                   'favicon.ico', mimetype='image/vnd.microsoft.icon')

class LoginForm(Form):
    email = TextField('Email', [Email(), Required()])
    password = PasswordField('Password', [Required()])

@app.route("/login", methods=['GET', 'POST'])
@feature_flag('PAYMENTS')
def login():
    form = LoginForm(request.form)
    if request.method == 'POST' and form.validate():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(request.args.get('next') or url_for('pay'))
        else:
            flash("Invalid login details!")
    return render_template("login.html", form=form)

class SignupForm(Form):
    name = TextField('Name', [Required()])
    email = TextField('Email', [Email(), Required()])
    password = PasswordField('Password', [Required(), EqualTo('confirm', message='Passwords do not match')])
    confirm = PasswordField('Confirm password', [Required()])

@app.route("/signup", methods=['GET', 'POST'])
@feature_flag('PAYMENTS')
def signup():
    form = SignupForm(request.form)
    if request.method == 'POST' and form.validate():
        user = User(form.email.data, form.name.data)
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError, e:
            raise
        login_user(user)
        return redirect(url_for('pay'))

    return render_template("signup.html", form=form)

class ForgotPasswordForm(Form):
    email = TextField('Email', [Email(), Required()])

    def validate_email(form, field):
        user = User.query.filter_by(email=form.email.data).first()
        if not user:
            raise ValidationError('Email address not found')
        form._user = user

@app.route("/forgot-password", methods=['GET', 'POST'])
@feature_flag('PAYMENTS')
def forgot_password():
    form = ForgotPasswordForm(request.form)
    if request.method == 'POST' and form.validate():
        if form._user:
            reset = PasswordReset(form.email.data)
            reset.new_token()
            db.session.add(reset)
            db.session.commit()
            msg = Message("EMF Camp password reset",
                sender=("EMF Camp 2012", "contact@emfcamp.org.uk"),
                recipients=[form.email.data])
            msg.body = render_template("reset-password-email.txt", user=form._user, reset=reset)
            mail.send(msg)

        return redirect(url_for('reset_password', email=form.email.data))
    return render_template("forgot-password.html", form=form)

class ResetPasswordForm(Form):
    email = TextField('Email', [Email(), Required()])
    token = TextField('Token', [Required()])
    password = PasswordField('New password', [Required(), EqualTo('confirm', message='Passwords do not match')])
    confirm = PasswordField('Confirm password', [Required()])

    def validate_token(form, field):
        reset = PasswordReset.query.filter_by(email=form.email.data, token=field.data).first()
        if not reset:
            raise ValidationError('Token not found')
        if reset.expired():
            raise ValidationError('Token has expired')
        form._reset = reset

@app.route("/reset-password", methods=['GET', 'POST'])
@feature_flag('PAYMENTS')
def reset_password():
    form = ResetPasswordForm(request.form, email=request.args.get('email'), token=request.args.get('token'))
    if request.method == 'POST' and form.validate():
        user = User.query.filter_by(email=form.email.data).first()
        db.session.delete(form._reset)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('pay'))
    return render_template("reset-password.html", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect('/')

class ChoosePrepayTicketsForm(Form):
    Prepay = TicketType.query.filter_by(name='Prepay Camp Ticket').one()
    count = IntegerSelectField('Number of tickets', [Required()], max=Prepay.limit)

    def validate_count(form, field):
        Prepay = TicketType.query.filter_by(name='Prepay Camp Ticket').one()
        paid = current_user.tickets.filter_by(type=Prepay, paid=True).count()
        if field.data < paid:
            raise ValidationError('You already have paid for %d tickets' % paid)

@app.route("/pay", methods=['GET', 'POST'])
@login_required
def pay():
    Prepay = TicketType.query.filter_by(name='Prepay Camp Ticket').one()
    
    # have they bought something?
    if "bought" not in session:
        session["bought"] = False

    if "count" not in session:
        session["count"] = 1

    form = ChoosePrepayTicketsForm(request.form, count=session["count"])

    if request.method == 'POST' and form.validate():
        count = form.count.data
        if count != session["count"]:
            session["count"] = count

        if session["count"] > 0:
            session["bought"] = True

        return redirect(url_for('pay'))

    tickets = {}
    ts = current_user.tickets.all()
    for t in ts:
        tickets[t.id] = {"expired": t.expired(), "paid": t.paid, "payment" : t.payment}

    return render_template("pay.html", form=form, total=session["count"] * Prepay.cost, tickets=tickets, bought=session["bought"])

def buy_some_tickets(provider, count):
    Prepay = TicketType.query.filter_by(name='Prepay Camp Ticket').one()
    p = Payment(provider, current_user)
    db.session.add(p)
    db.session.commit()

    for i in range(0, count):
        current_user.tickets.append(Ticket(type_id=Prepay.id, payment=p))
        db.session.add(current_user)
        db.session.commit()

    return p

@app.route("/sponsors")
def sponsors():
    return render_template('sponsors.html')

@app.route("/about/company")
def company():
    return render_template('company.html')

@app.route("/pay/gocardless-start")
@feature_flag('PAYMENTS')
@login_required
def gocardless_start():
    unpaid = session["count"]
    Prepay = TicketType.query.filter_by(name='Prepay Camp Ticket').one()
    payment = buy_some_tickets("GoCardless", unpaid)
    amount = Prepay.cost * unpaid

    bill_url = gocardless.client.new_bill_url(amount, name="Electromagnetic Field Ticket Deposit", state=payment.id)

    return redirect(bill_url)

@app.route("/pay/gocardless-complete")
@feature_flag('PAYMENTS')
@login_required
def gocardless_complete():
    try:
        gocardless.client.confirm_resource(request.args)
    except (gocardless.exceptions.ClientError, gocardless.exceptions.SignatureError) as e:
        app.logger.exception("userid: %d: Gocardless-complete exception %s" % (current_user.id, e))
        flash("An error occurred with your payment, please contact info@emfcamp.org")
        return redirect(url_for('main'))

    if request.args["resource_type"] != "bill":
        app.logger.error("Gocardless-complete didn't get a bill!" % (str(request.args)))
        try:
            app.logger.error("Gocardless-complete: userid %d" % (current_user.id))
        except:
            pass
        
    state = session["count"]
    session.pop("count", None)
    session.pop("bought", None)

    payment_id = request.args["state"]
    gcid = request.args["resource_id"]
    # TODO send an email with the details.
    # should we send the resource_uri in the bill email?
    app.logger.info("user %d started gocardless payment for %s, gc reference %s" % (current_user.id, payment_id, gcid))

    try:
        payment = Payment.query.filter_by(id=payment_id).one()
    except Exception, e:
        app.logger.error("Exception getting gocardless payment %s: %s" % (payment_id, e))
        flash("An error occurred with your payment, please contact info@emfcamp.org")
        return redirect(url_for('main'))

    # keep the gocardless reference so we can find the payment when we get called by the webhook
    payment.extra = gcid
    payment.state = "inprogress"
    db.session.add(payment)
    db.session.commit()

    return render_template('gocardless-complete.html', paid=state, gcref=gcid)

#
# it's just a link? see ticket #17
#
@app.route("/pay/gocardless-cancel")
@feature_flag('PAYMENTS')
@login_required
def gocardless_cancel():
    print request.args
    print request
    try:
        gocardless.client.confirm_resource(request.args)
    except (gocardless.exceptions.ClientError, gocardless.exceptions.SignatureError) as e:
        app.logger.exception("userid: %d: Gocardless-cancel exception %s" % (current_user.id, e))
        flash("An error occurred with your payment, please contact info@emfcamp.org")
        return redirect(url_for('main'))

    if request.args["resource_type"] != "bill":
        app.logger.error("Gocardless-cancel didn't get a bill!" % (str(request.args)))
        try:
            app.logger.error("Gocardless-cancel: userid %d" % (current_user.id))
        except:
            pass

    state = session["count"]
    session.pop("count", None)
    session.pop("bought", None)

    payment_id = request.args["state"]
    # TODO send an email with the details.
    # should we send the resource_uri in the bill email?
    app.logger.info("user %d canceled gocardless payment for %s" % (current_user.id, payment_id))
    payment = Payment.query.filter_by(id=payment_id).one()
    tc = 0
    for t in payment.tickets:
        db.session.delete(t)
        tc += 1

    db.session.delete(p)
    db.session.commit()

    return render_template('gocardless-cancel.html', paid=tc)

@app.route("/gocardless-webhook", methods=['POST'])
@feature_flag('PAYMENTS')
def gocardless_webhook():
    """
        handle the gocardless webhook / callback callback:
        https://gocardless.com/docs/web_hooks_guide#response
        
        we mostly want 'bill'
        
        GoCardless limits the webhook to 5 secs. this should run async...

    """
    ret = ("", 403)
    json_data = simplejson.loads(request.data)

    if gocardless.client.validate_webhook(json_data['payload']):
        data = json_data['payload']
        # action can be:
        #
        # paid -> money taken from the customers account, at this point we concider the ticket paid.
        # created -> for subscriptions
        # failed -> customer is broke
        # withdrawn -> we actually get the money
        if data['resource_type'] == 'bill' and data['action'] == 'paid':
            for bill in data['bills']:
                # process each bill record

                # this is the same as the resource_id
                # we get from the gocardless-complete redirect
                id = bill['id']
                payment = Payment.query.filter_by(extra=id).one()
                ts = payment.tickets.all()

                app.logger.info("GoCardless payment for user %d has been paid. gcref %s, our ref %s, %d tickets" % (payment.user.id, id, payment.reference, len(ts)))
                
                if payment.state != "inprogress":
                    app.logger.warning("GoCardless bill payment %s, payment state was %s, we expected 'inprogress'" % (id, payment.state) )

                for t in ts:
                    t.paid=True
                    db.session.add(t)
                
                payment.state = "paid"
                db.session.add(payment)
                db.session.commit()
                
                # TODO email the user

            return ("", 200)
        elif data['resource_type'] == 'bill' and data['action'] == 'withdrawn':
            for bill in data['bills']:
                print bill
                id = bill['id']
                payment = Payment.query.filter_by(extra=id).one()
                app.logger.info("GoCardless payment for user %d has been withdrawn. gcref %s, our ref %s" % (payment.user.id, id, payment.reference))
            return ("", 200)
        elif data['resource_type'] == 'bill' and data['action'] == 'failed':
            for bill in data['bills']:
                print bill
                id = bill['id']
                payment = Payment.query.filter_by(extra=id).one()
                app.logger.info("GoCardless payment for user %d has failed. gcref %s, our ref %s" % (payment.user.id, id, payment.reference))
            return ("", 200)

    return ret

@app.route("/pay/transfer-start")
@feature_flag('PAYMENTS')
@login_required
def transfer_start():
    unpaid = session["count"]
    Prepay = TicketType.query.filter_by(name='Prepay Camp Ticket').one()
    payment = buy_some_tickets("BankTransfer", unpaid)
    amount = Prepay.cost * unpaid
    
    # XXX TODO send an email with the details.
    app.logger.info("user %d started BankTransfer payment for %s" % (current_user.id, payment.bankref))

    session.pop("count", None)
    session.pop("bought", None)
    return render_template('transfer-start.html', amount=amount, bankref=payment.bankref)

@app.route("/pay/terms")
def ticket_terms():
    return render_template('terms.html')
