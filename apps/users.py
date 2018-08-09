import re
import time

from flask import (
    render_template, redirect, request, flash,
    url_for, abort, Blueprint, current_app as app,
    session, Markup, render_template_string,
)
from flask_login import (
    login_user, login_required, logout_user, current_user,
)
from flask_mail import Message
from sqlalchemy import or_
from wtforms import StringField, HiddenField, SubmitField, BooleanField
from wtforms.fields.html5 import EmailField
from wtforms.validators import Required, Email, ValidationError

from main import db, mail
from models.user import User, UserDiversity, verify_signup_code
from models.cfp import Proposal, CFPMessage
from models.purchase import Purchase
from models.payment import Payment
from models.basket import Basket

from .common import (
    set_user_currency, feature_flag,
)
from .common.forms import Form


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
    email = EmailField('Email', [Email(), Required()])
    next = NextURLField('Next')

    def validate_email(form, field):
        user = User.get_by_email(form.email.data)
        if user is None:
            raise ValidationError('Email address not found')
        form._user = user

@users.route('/login/<email>')
@feature_flag('BYPASS_LOGIN')
def login_by_email(email):
    user = User.get_by_email(email)

    if current_user.is_authenticated:
        logout_user()

    if user is None:
        flash("Your email address was not recognised")
    else:
        login_user(user)
        session.permanent = True

    return redirect(request.args.get('next', url_for('.account')))


@users.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(request.args.get('next', url_for('.account')))

    if request.args.get('code'):
        user = User.get_by_code(app.config['SECRET_KEY'], request.args.get('code'))
        if user is not None:
            login_user(user)
            session.permanent = True
            return redirect(request.args.get('next', url_for('.account')))
        else:
            flash("Your login link was invalid. Please enter your email address below to receive a new link.")

    form = LoginForm(request.form, next=request.args.get('next'))
    if form.validate_on_submit():
        code = form._user.login_code(app.config['SECRET_KEY'])

        msg = Message('Electromagnetic Field: Login details',
                      sender=app.config['TICKETS_EMAIL'],
                      recipients=[form._user.email])
        msg.body = render_template('emails/login-code.txt', user=form._user,
                                    code=code, next_url=request.args.get('next'))
        mail.send(msg)

        flash("We've sent you an email with your login link")

    if request.args.get('email'):
        form.email.data = request.args.get('email')

    return render_template("account/login.html", form=form, next=request.args.get('next'))


@users.route("/logout")
@login_required
def logout():
    session.permanent = False
    Basket.clear_from_session()
    logout_user()
    return redirect(url_for('base.main'))


class SignupForm(Form):
    email = EmailField('Email', [Email(), Required()])
    name = StringField('Name', [Required()])
    allow_promo = BooleanField('Send me occasional emails about future EMF events')
    signup = SubmitField('Sign up')

    def validate_email(form, field):
        if User.does_user_exist(field.data):
            field.was_duplicate = True

            msg = Markup(
                render_template_string('Account already exists. '
                                       'Please <a href="{{ url }}">click here</a> to log in.',
                                       url=url_for('users.login', email=field.data)))
            raise ValidationError(msg)


@users.route("/signup", methods=['GET', 'POST'])
def signup():
    if not request.args.get('code'):
        abort(404)

    uid = verify_signup_code(app.config['SECRET_KEY'], time.time(), request.args.get('code'))
    if uid is None:
        flash("Your signup link was invalid. Please note that they expire after 6 hours.")
        abort(404)

    user = User.query.get_or_404(uid)
    if not user.has_permission('admin'):
        app.logger.warn("Signup link resolves to non-admin user %s", user)
        abort(404)

    form = SignupForm()

    if current_user.is_authenticated:
        return redirect(url_for('.account'))

    if form.validate_on_submit():
        email, name = form.email.data, form.name.data
        user = User(email, name)

        if form.allow_promo.data:
            user.promo_opt_in = True

        db.session.add(user)
        db.session.commit()
        app.logger.info('Signed up new user with email %s and id %s',
                        email, user.id)

        msg = Message('Welcome to the EMF website',
                      sender=app.config['CONTACT_EMAIL'],
                      recipients=[email])
        msg.body = render_template('emails/signup-user.txt', user=user)
        mail.send(msg)

        login_user(user)

        return redirect(url_for('.account'))

    if request.args.get('email'):
        form.email.data = request.args.get('email')

    return render_template("account/signup.html", form=form)


@users.route("/set-currency", methods=['POST'])
def set_currency():
    if request.form['currency'] not in ('GBP', 'EUR'):
        abort(400)

    set_user_currency(request.form['currency'])
    db.session.commit()
    return redirect(url_for('tickets.main'))


class AccountForm(Form):
    name = StringField('Name', [Required()])
    allow_promo = BooleanField('Send me occasional emails about future EMF events')

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
        current_user.promo_opt_in = form.allow_promo.data

        current_user.diversity.age = form.age.data
        current_user.diversity.gender = form.gender.data
        current_user.diversity.ethnicity = form.ethnicity.data

        app.logger.info('%s updated user information', current_user.name)
        db.session.commit()

        flash("Your details have been saved.")
        return redirect(url_for('.account'))

    if request.method != 'POST':
        # This is a required field so should always be set
        form.name.data = current_user.name
        form.allow_promo.data = current_user.promo_opt_in

        if current_user.diversity:
            form.age.data = current_user.diversity.age
            form.gender.data = current_user.diversity.gender
            form.ethnicity.data = current_user.diversity.ethnicity

    unread_count = CFPMessage.query\
        .join(Proposal)\
        .filter(Proposal.user_id == current_user.id,
                Proposal.id == CFPMessage.proposal_id,
                CFPMessage.is_to_admin.is_(False),
                or_(CFPMessage.has_been_read.is_(False),
                    CFPMessage.has_been_read.is_(None)))\
        .count()

    return render_template("account/main.html", form=form, unread_count=unread_count)


@users.route('/account/tickets')
def purchases_redirect():
    return redirect(url_for('.purchases'))


@users.route('/account/purchases', methods=['GET', 'POST'])
@login_required
def purchases():
    purchases = current_user.owned_purchases \
                            .filter(~Purchase.state.in_(['cancelled', 'reserved'])) \
                            .order_by(Purchase.id)

    tickets = purchases.filter_by(is_ticket=True).all()
    other_items = purchases.filter_by(is_ticket=False).all()

    payments = current_user.payments.filter(Payment.state != "cancelled") \
                                    .order_by(Payment.id).all()

    if not tickets and not payments:
        return redirect(url_for('tickets.main'))

    transferred_to = current_user.transfers_to
    transferred_from = current_user.transfers_from

    show_receipt = any([t for t in tickets if t.is_paid_for is True])

    return render_template("account/purchases.html",
                           tickets=tickets,
                           other_items=other_items,
                           payments=payments,
                           show_receipt=show_receipt,
                           transferred_to=transferred_to,
                           transferred_from=transferred_from)


@users.route("/sso/<site>")
def sso(site=None):

    volunteer_sites = [app.config['VOLUNTEER_SITE']]
    if 'VOLUNTEER_CAMP_SITE' in app.config:
        volunteer_sites.append(app.config['VOLUNTEER_CAMP_SITE'])

    if site not in volunteer_sites:
        abort(404)

    if not current_user.is_authenticated:
        return redirect(url_for('.login', next=url_for('.sso', site=site)))

    key = app.config['VOLUNTEER_SECRET_KEY']
    sso_code = current_user.sso_code(key)

    return redirect('https://%s/?p=sso&c=%s' % (site, sso_code))

