from flask import (
    render_template, redirect, request, flash,
    url_for, abort, Blueprint, current_app as app
)
from flask.ext.login import (
    login_user, login_required, logout_user, current_user,
)
from flask_mail import Message
from wtforms.validators import Required, Email, EqualTo, ValidationError
from wtforms import StringField, PasswordField, HiddenField, SubmitField
from sqlalchemy.exc import IntegrityError

from main import db, mail
from common import set_user_currency, feature_flag, create_current_user, send_template_email
from .common.forms import Form
from models.user import User, PasswordReset, UserDiversity
import re

users = Blueprint('users', __name__)


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
    #  password = PasswordField('Password', [Required()])
    next = NextURLField('Next')


@users.route("/login", methods=['GET', 'POST'])
@feature_flag('TICKET_SALES')
def login():
    if current_user.is_authenticated():
        return redirect(request.args.get('next', url_for('tickets.main')))

    if request.args.get('code'):
        user = User.get_by_code(app.config['SECRET_KEY'], request.args.get('code'))
        if user is not None:
            login_user(user)
            return redirect(request.args.get('next', url_for('tickets.main')))
        else:
            flash("Your login link was invalid. Please note that they expire after 6 hours.")

    form = LoginForm(request.form, next=request.args.get('next'))
    if request.method == 'POST' and form.validate():
        user = User.query.filter_by(email=form.email.data).one()
        if user:
            code = user.login_code(app.config['SECRET_KEY'])
            send_template_email('Electromagnetic Field: Login details', user.email,
                                app.config['TICKETS_EMAIL'], 'emails/login-code.txt',
                                user=user, code=code, next_url=request.args.get('next'))
            flash("We've sent you an email with your login link")
        else:
            flash("Invalid login details!")

    if request.args.get('email'):
        form.email.data = request.args.get('email')

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


@users.route("/signup", methods=['GET', 'POST'])
@feature_flag('TICKETS_SITE')
@feature_flag('TICKET_SALES')
def signup():
    if current_user.is_authenticated():
        return redirect(url_for('tickets.main'))
    form = SignupForm(request.form, next=request.args.get('next'))

    if request.method == 'POST' and form.validate():
        try:
            create_current_user(form.email.data, form.name.data, form.password.data)
        except IntegrityError as e:
            app.logger.warn('Adding user raised %r, possible double-click', e)
            flash('An error occurred adding your account. Please try again.')
            return redirect(url_for('users.signup'))

        return redirect(form.next.data or url_for('tickets.main'))

    return render_template("signup.html", form=form, existing_email=request.args.get('existing_email'))


class ForgotPasswordForm(Form):
    email = StringField('Email', [Email(), Required()])

    def validate_email(form, field):
        user = User.query.filter_by(email=form.email.data).first()
        if not user:
            raise ValidationError('Email address not found')
        form._user = user


@users.route("/forgot-password", methods=['GET', 'POST'])
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

        return redirect(url_for('users.reset_password', email=form.email.data))
    return render_template("forgot-password.html", form=form)


class ResetPasswordForm(Form):
    email = StringField('Email', [Email(), Required()])
    token = StringField('Token', [Required()])
    password = PasswordField('New password', [Required(),
                                              EqualTo('confirm', message='Passwords do not match')])
    confirm = PasswordField('Confirm password', [Required()])

    def validate_token(form, field):
        reset = PasswordReset.query.filter_by(email=form.email.data, token=field.data).first()
        if not reset:
            raise ValidationError('Token not found')
        if reset.expired():
            raise ValidationError('Token has expired')
        form._reset = reset


@users.route("/reset-password", methods=['GET', 'POST'])
@feature_flag('TICKETS_SITE')
@feature_flag('TICKET_SALES')
def reset_password():
    form = ResetPasswordForm(request.form, email=request.args.get('email'), token=request.args.get('token'))
    if request.method == 'POST' and form.validate():
        user = User.query.filter_by(email=form.email.data).first()
        db.session.delete(form._reset)
        user.set_password(form.password.data)
        db.session.commit()
        return redirect(url_for('users.login'))
    return render_template("reset-password.html", form=form)


@users.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('base.main'))


@users.route("/set-currency", methods=['POST'])
@feature_flag('TICKETS_SITE')
def set_currency():
    if request.form['currency'] not in ('GBP', 'EUR'):
        abort(400)

    set_user_currency(request.form['currency'])
    return redirect(url_for('tickets.choose'))


class AccountForm(Form):
    name = StringField('Name', [Required()])
    age = StringField('Age')
    gender = StringField('Gender')
    ethnicity = StringField('Ethnicity')

    forward = SubmitField('Update')

@users.route("/account", methods=['GET', 'POST'])
@login_required
def account():
    form = AccountForm()

    if form.validate_on_submit():
        if not current_user.diversity:
            current_user.diversity = UserDiversity()
            current_user.diversity.user_id = current_user.id
            db.session.add(current_user.diversity)

        current_user.name = form.name.data
        current_user.diversity.age = form.age.data
        current_user.diversity.gender = form.gender.data
        current_user.diversity.ethnicity = form.ethnicity.data

        db.session.commit()

    # This is a required field so should always be set
    form.name.data = current_user.name

    if current_user.diversity:
        form.age.data = current_user.diversity.age
        form.gender.data = current_user.diversity.gender
        form.ethnicity.data = current_user.diversity.ethnicity

    return render_template("account.html", form=form)
