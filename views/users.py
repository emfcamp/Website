from main import app, db, mail, login_manager
from views import (
    set_user_currency, Form, feature_flag,
    create_current_user,
)
from models.user import User, PasswordReset

from flask import (
    render_template, redirect, request, flash,
    url_for, abort, _request_ctx_stack
)
from flask.ext.login import (
    login_user, login_required, logout_user, current_user,
)
from flask_mail import Message

from wtforms.validators import Required, Email, EqualTo, ValidationError
from wtforms import StringField, PasswordField, HiddenField

from sqlalchemy.exc import IntegrityError

import re

login_manager.setup_app(app, add_context_processor=True)
app.login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(userid):
    user = User.query.filter_by(id=userid).first()
    if user:
        _request_ctx_stack.top.user_email = user.email
    return user


class NextURLField(HiddenField):
    def _value(self):
        # Cheap way of ensuring we don't get absolute URLs
        if not self.data or '//' in self.data:
            return ''
        if not re.match('^[-_0-9a-zA-Z/?=&]+$', self.data):
            app.logger.error('Dropping next URL %s', repr(self.data))
            return ''
        return self.data

class LoginForm(Form):
    email = StringField('Email', [Email(), Required()])
    password = PasswordField('Password', [Required()])
    next = NextURLField('Next')

@app.route("/login", methods=['GET', 'POST'])
@feature_flag('TICKET_SALES')
def login():
    if current_user.is_authenticated():
        return redirect(request.args.get('next', url_for('tickets')))
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
    name = StringField('Full name', [Required()])
    email = StringField('Email', [Email(), Required()])
    password = PasswordField('Password', [Required(), EqualTo('confirm', message='Passwords do not match')])
    confirm = PasswordField('Confirm password', [Required()])

    next = NextURLField('Next')

    def validate_email(form, field):
        if current_user.is_anonymous() and User.does_user_exist(field.data):
            field.was_duplicate = True
            raise ValidationError('Account already exists')

@app.route("/signup", methods=['GET', 'POST'])
@feature_flag('TICKETS_SITE')
@feature_flag('TICKET_SALES')
def signup():
    if current_user.is_authenticated():
        return redirect(url_for('tickets'))
    form = SignupForm(request.form, next=request.args.get('next'))

    if request.method == 'POST' and form.validate():
        try:
            create_current_user(form.email.data, form.name.data, form.password.data)
        except IntegrityError as e:
            app.logger.warn('Adding user raised %r, possible double-click', e)
            flash('An error occurred adding your account. Please try again.')
            return redirect(url_for('signup'))

        return redirect(form.next.data or url_for('tickets'))

    return render_template("signup.html", form=form, existing_email=request.args.get('existing_email'))


class ForgotPasswordForm(Form):
    email = StringField('Email', [Email(), Required()])

    def validate_email(form, field):
        user = User.query.filter_by(email=form.email.data).first()
        if not user:
            raise ValidationError('Email address not found')
        form._user = user

@app.route("/forgot-password", methods=['GET', 'POST'])
@feature_flag('TICKETS_SITE')
@feature_flag('TICKET_SALES')
def forgot_password():
    form = ForgotPasswordForm(request.form, email=request.args.get('email'))
    if request.method == 'POST' and form.validate():
        if form._user:
            reset = PasswordReset(form.email.data)
            reset.new_token()
            db.session.add(reset)
            db.session.commit()
            msg = Message("EMF password reset",
                sender=app.config['TICKETS_EMAIL'],
                recipients=[form.email.data])
            msg.body = render_template("emails/reset-password-email.txt", user=form._user, reset=reset)
            mail.send(msg)

        return redirect(url_for('reset_password', email=form.email.data))
    return render_template("forgot-password.html", form=form)

class ResetPasswordForm(Form):
    email = StringField('Email', [Email(), Required()])
    token = StringField('Token', [Required()])
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
@feature_flag('TICKETS_SITE')
@feature_flag('TICKET_SALES')
def reset_password():
    form = ResetPasswordForm(request.form, email=request.args.get('email'), token=request.args.get('token'))
    if request.method == 'POST' and form.validate():
        user = User.query.filter_by(email=form.email.data).first()
        db.session.delete(form._reset)
        user.set_password(form.password.data)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template("reset-password.html", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('main'))

@app.route("/set-currency", methods=['POST'])
@feature_flag('TICKETS_SITE')
def set_currency():
    if request.form['currency'] not in ('GBP', 'EUR'):
        abort(400)

    set_user_currency(request.form['currency'])
    return redirect(url_for('tickets_choose'))
