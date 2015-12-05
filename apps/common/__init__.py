# encoding=utf-8
from decorator import decorator
from datetime import datetime

from main import db, mail, external_url
from flask import session, render_template, abort, current_app as app
from flask.ext.login import login_user, current_user

from models.ticket import Ticket, TicketType
from models.site_state import get_site_state, get_sales_state
from models import User

from flask_mail import Message


class Currency(object):
    def __init__(self, code, symbol):
        self.code = code
        self.symbol = symbol

CURRENCIES = [
    Currency('GBP', u'£'),
    Currency('EUR', u'€'),
]
CURRENCY_SYMBOLS = dict((c.code, c.symbol) for c in CURRENCIES)


def load_utility_functions(app_obj):
    @app_obj.template_filter('price')
    def format_price(amount, currency, after=False):
        amount = u'{0:.2f}'.format(amount)
        symbol = CURRENCY_SYMBOLS[currency]
        if after:
            return amount + symbol
        return symbol + amount

    @app_obj.template_filter('bankref')
    def format_bankref(bankref):
        return '%s-%s' % (bankref[:4], bankref[4:])

    @app_obj.template_filter('gcid')
    def format_gcid(gcid):
        if len(gcid) > 12:
            return 'ending %s' % gcid[-12:]
        return gcid

    @app_obj.context_processor
    def utility_processor():
        now = datetime.utcnow()
        SALES_STATE = get_sales_state(now)
        SITE_STATE = get_site_state(now)
        return dict(
            SALES_STATE=SALES_STATE,
            SITE_STATE=SITE_STATE,
            CURRENCIES=CURRENCIES,
            CURRENCY_SYMBOLS=CURRENCY_SYMBOLS,
            external_url=external_url
        )

    @app_obj.context_processor
    def currency_processor():
        currency = get_user_currency()
        return {'user_currency': currency}

def send_template_email(subject, to, sender, template, **kwargs):
    msg = Message(subject, recipients=[to], sender=sender)
    msg.body = render_template(template, **kwargs)
    mail.send(msg)


def create_current_user(email, name, password=None):
    user = User(email, name)
    if password:
        user.set_password(password)
    else:
        user.generate_random_password()

    db.session.add(user)
    db.session.commit()
    app.logger.info('Created new user with email %s and id: %s', email, user.id)

    # Login & make sure everything's set correctly
    login_user(user)
    assert current_user.id == user.id
    current_user.id = user.id
    return user


def get_user_currency(default='GBP'):
    return session.get('currency', default)


def set_user_currency(currency):
    session['currency'] = currency


# This avoids adding tickets to the db so should avoid a lot of auto-flush
# problems, unless you need the tickets persisted, use this.
def get_basket_and_total():
    basket = [TicketType.query.get(id) for id in session.get('basket', [])]
    total = sum(tt.get_price(get_user_currency()) for tt in basket)
    app.logger.debug('Got basket %s with total %s', basket, total)
    return basket, total


# This actually adds the user's tickets to the database. This should only be used
# just before a ticket is bought
def process_basket():
    user_id = current_user.id
    items, total = get_basket_and_total()

    basket = [Ticket(type=tt, user_id=user_id) for tt in items]
    app.logger.debug('Added tickets to db for basket %s with total %s', basket, total)
    return basket, total


def feature_flag(flag):
    def call(f, *args, **kw):
        if app.config.get(flag, False) is True:
            return f(*args, **kw)
        return abort(404)
    return decorator(call)
