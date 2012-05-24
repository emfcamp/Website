from main import app, db, gocardless, mail, Prepay
from models.user import User, PasswordReset
from models.payment import Payment
from models.ticket import TicketType, Ticket
from flask import render_template, redirect, request, flash, url_for, abort
from flaskext.login import login_user, login_required, logout_user, current_user
from flaskext.mail import Message
from flaskext.wtf import \
    Form, Required, Email, EqualTo, ValidationError, \
    TextField, PasswordField, SelectField
from sqlalchemy.exc import IntegrityError
from decorator import decorator
import simplejson

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
    count = IntegerSelectField('Number of tickets', [Required()], max=Prepay.limit)

    def validate_count(form, field):
        paid = current_user.tickets.filter_by(type=Prepay, paid=True).count()
        if field.data < paid:
            raise ValidationError('You already have paid for %d tickets' % paid)

@app.route("/pay", methods=['GET', 'POST'])
@login_required
def pay():
    #
    # this list all tickets, even ones that have been paid
    # we might be better off with ", paid=False" on the end to avoid confusion.
    # 
    prepays = current_user.tickets.filter_by(type=Prepay)

    count = prepays.count()
    if not count:
        current_user.tickets.append(Ticket(type_id=Prepay.id))
        db.session.add(current_user)
        db.session.commit()
        count = 1

    form = ChoosePrepayTicketsForm(request.form, count=count)

    if request.method == 'POST' and form.validate():
        count = form.count.data
        if count > prepays.count():
            for i in range(prepays.count(), count):
                current_user.tickets.append(Ticket(type_id=Prepay.id))
        elif count < prepays.count():
            for i in range(count, prepays.count()):
                db.session.delete(current_user.tickets[i])

        db.session.add(current_user)
        db.session.commit()
        return redirect(url_for('pay'))

    tickets = {}
    ts = current_user.tickets.all()
    for t in ts:
        tickets[t.id] = {"expired": t.expired(), "paid": t.paid}

    return render_template("pay.html", form=form, total=count * Prepay.cost, tickets=tickets)


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
    unpaid = current_user.tickets.filter_by(paid=False)
    amount = sum(t.type.cost for t in unpaid.all())
    bill_url = gocardless.client.new_bill_url(amount, name="Electromagnetic Field Ticket Deposit", state="ppc_" + str(unpaid.count()))
    return render_template('gocardless-start.html', bill_url=bill_url)

@app.route("/pay/gocardless-complete")
@feature_flag('PAYMENTS')
@login_required
def gocardless_complete():
    try:
        gocardless.client.confirm_resource(request.args)
    except gocardless.exceptions.ClientError:
        app.logger.exception("Gocardless-complete exception")
        flash("An error occurred with your payment, please contact info@emfcamp.org")
        return redirect(url_for('main'))
        
    state = request.args["state"]
    state = int(state[4:])
    return render_template('gocardless-complete.html', paid=state)

@app.route("/gocardless-webhook", methods=['POST'])
@feature_flag('PAYMENTS')
def gocardless_webhook():
        """
        handle the gocardless webhook / callback callback:
        https://gocardless.com/docs/web_hooks_guide#response
        
        we mostly want 'bill'

        XXX TODO logging        
    """
    ret = ("", 403)
    json_data = simplejson.loads(request.data)
    if gocardless.client.validate_webhook(json_data['payload']):
        data = json_data['payload']
        if data['resource_type'] == 'bill' and data['action'] == 'paid':
            for bill in data['bills']:
                # process the bill
                pass
        ret = ("", 200)
    return ret
    
@app.route("/pay/gocardless-cancel")
@feature_flag('PAYMENTS')
@login_required
def gocardless_cancel():
    return render_template('gocardless-cancel.html')

@app.route("/pay/transfer-start")
@feature_flag('PAYMENTS')
@login_required
def transfer_start():
    unpaid = current_user.tickets.filter_by(paid=False)
    amount = sum(t.type.cost for t in unpaid.all())
    return render_template('transfer-start.html', amount=amount)

@app.route("/pay/terms")
def ticket_terms():
    return render_template('terms.html')
