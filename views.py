from main import app, db, gocardless, mail
from models.user import User, PasswordReset
from models.payment import Payment
from models.ticket import TicketType, Ticket
from flask import render_template, redirect, request, flash, url_for, abort
from flaskext.login import login_user, login_required, logout_user
from flaskext.mail import Message
from flaskext.wtf import Form, TextField, PasswordField, IntegerField, Required, Email, EqualTo, ValidationError
from sqlalchemy.exc import IntegrityError
from decorator import decorator
from wtforms.fields.core import UnboundField

import code

def feature_flag(flag):
    def call(f, *args, **kw):
        if app.config.get(flag, False) == True:
            return f(*args, **kw)
        return abort(404)
    return decorator(call)

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
        if user is None or not user.check_password(form.password.data):
            flash("Invalid login details!")
            return redirect(url_for('login'))
        login_user(user)
        return redirect(url_for('pay'))
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

@app.route("/pay")
@login_required
def pay():
    return render_template("pay.html")


@app.route("/sponsors")
def sponsors():
    return render_template('sponsors.html')

@app.route("/about/company")
def company():
    return render_template('company.html')

@app.route("/pay/gocardless-start")
@feature_flag('PAYMENTS')
def gocardless_start():
    bill_url = gocardless.client.new_bill_url(40.00, name="Electromagnetic Field Ticket Deposit")
    return render_template('gocardless-start.html', bill_url=bill_url)

@app.route("/pay/gocardless-complete")
@feature_flag('PAYMENTS')
def gocardless_complete():
    try:
        gocardless.client.confirm_resource(request.args)
    except gocardless.exceptions.ClientError:
        app.logger.exception("Gocardless-complete exception")
        flash("An error occurred with your payment, please contact info@emfcamp.org")
        return redirect(url_for('main'))
    return render_template('gocardless-complete.html')

@app.route("/pay/gocardless-cancel")
@feature_flag('PAYMENTS')
def gocardless_cancel():
    return render_template('gocardless-cancel.html')

@app.route("/pay/transfer-start")
@feature_flag('PAYMENTS')
def transfer_start():
    return render_template('transfer-start.html')

@app.route("/pay/terms")
def ticket_terms():
    return render_template('terms.html')

class BuyTicketForm(Form):
    def __init__(self, *args, **kwargs):
        # clear the form out and recreate it if already created.
        if len(self._unbound_fields) > 1:
            tmp = self._unbound_fields[0]
            self._unbound_fields = [tmp,]

        #
        # doing this everytime is probably bad for performance?
        # is there an sql query caching layer?            
        ticket_types = TicketType.query.all()
        for i, tt in enumerate(ticket_types):
            # why can't simple things be simple?
            #
            # cant work out how to pass in cost as well so shove it in description.
            #
            self._unbound_fields.append(('tt_%s' % tt.id, UnboundField(IntegerField, default = 0, label = tt.name, description = "%2.02f" % (tt.cost)) ))

        super(BuyTicketForm, self).__init__(*args, **kwargs)

@app.route("/buy/tickets", methods=['GET', 'POST'])
@feature_flag('PAYMENTS')
@login_required
def buy_tickets():
    form = BuyTicketForm(request.form)
    if request.method == 'POST' and form.validate():
        """do the form"""
        total_cost = 0
        
        id2tt = {}
        tts = TicketType.query.all()
        for t in tts:
            id2tt[t.id] = t

        for i in form:
            if i.id.startswith("tt_") and i.data > 0:
                id = int(i.id[3:])
                tt = id2tt[id]
                print tt.name, tt.cost, i.data
                total_cost += tt.cost * i.data
                
#        code.interact(local=locals())
        print "total cost: %.02f" % (total_cost)

    return render_template("buy-tickets.html", form=form)

