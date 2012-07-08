from main import app, db, gocardless, mail
from models.user import User, PasswordReset

from sqlalchemy.exc import IntegrityError

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

from datetime import datetime, timedelta
import re

class NextURLField(HiddenField):
    def _value(self):
        # Cheap way of ensuring we don't get absolute URLs
        if not self.data or '//' in self.data:
            return ''
        if not re.match('^[-a-z/?=&]+$', self.data):
            return ''
        return self.data

class LoginForm(Form):
    email = TextField('Email', [Email(), Required()])
    password = PasswordField('Password', [Required()])
    next = NextURLField('Next')

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated():
        return redirect(url_for('tickets'))
    form = LoginForm(request.form, next=request.args.get('next'))
    if request.method == 'POST' and form.validate():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            return redirect(form.next.data or url_for('tickets'))
        else:
            flash("Invalid login details!")
    return render_template("login.html", form=form)

class SignupForm(Form):
    name = TextField('Full name', [Required()])
    email = TextField('Email', [Email(), Required()])
    password = PasswordField('Password', [Required(), EqualTo('confirm', message='Passwords do not match')])
    confirm = PasswordField('Confirm password', [Required()])
    next = NextURLField('Next')

@app.route("/signup", methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated():
        return redirect(url_for('tickets'))
    form = SignupForm(request.form, next=request.args.get('next'))

    if request.method == 'POST' and form.validate():
        user = User(form.email.data, form.name.data)
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError, e:
            flash("Email address %s is already in use, please use another or reset your password" % (form.email.data))
            return redirect(url_for('signup'))
        login_user(user)

        # send a welcome email.
        msg = Message("Welcome to Electromagnetic Field",
                sender=app.config.get('TICKETS_EMAIL'),
                recipients=[user.email])
        msg.body = render_template("welcome-email.txt", user=user)
        mail.send(msg)

        return redirect(form.next.data or url_for('tickets'))

    return render_template("signup.html", form=form)

class ForgotPasswordForm(Form):
    email = TextField('Email', [Email(), Required()])

    def validate_email(form, field):
        user = User.query.filter_by(email=form.email.data).first()
        if not user:
            raise ValidationError('Email address not found')
        form._user = user

@app.route("/forgot-password", methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordForm(request.form)
    if request.method == 'POST' and form.validate():
        if form._user:
            reset = PasswordReset(form.email.data)
            reset.new_token()
            db.session.add(reset)
            db.session.commit()
            msg = Message("EMF password reset",
                sender=app.config.get('TICKETS_EMAIL'),
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
def reset_password():
    form = ResetPasswordForm(request.form, email=request.args.get('email'), token=request.args.get('token'))
    if request.method == 'POST' and form.validate():
        user = User.query.filter_by(email=form.email.data).first()
        db.session.delete(form._reset)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('tickets'))
    return render_template("reset-password.html", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('main'))

@app.route("/set-currency", methods=['POST'])
def set_currency():
    if request.form['currency'] not in ('GBP', 'EUR'):
        abort(400)

    session['currency'] = request.form['currency']
    return redirect(url_for('tickets_choose'))
