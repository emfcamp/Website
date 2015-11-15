# encoding=utf-8
from main import app, external_url
from flask import session, abort

from models.ticket import Ticket, TicketType
from models.site_state import get_site_state, get_sales_state

from flask_wtf import Form as BaseForm
from flask_wtf.form import _is_hidden
from flask.ext.login import current_user
from wtforms import (
    IntegerField, SelectField, HiddenField,
)
from wtforms.widgets import Input
from wtforms.fields import StringField
from wtforms.compat import string_types

from decorator import decorator
from datetime import datetime


class IntegerSelectField(SelectField):
    def __init__(self, *args, **kwargs):
        kwargs['coerce'] = int
        self.fmt = kwargs.pop('fmt', str)
        self.values = kwargs.pop('values', [])
        SelectField.__init__(self, *args, **kwargs)

    @property
    def values(self):
        return self._values

    @values.setter
    def values(self, vals):
        self._values = vals
        self.choices = [(i, self.fmt(i)) for i in vals]


class HiddenIntegerField(HiddenField, IntegerField):
    """
    widget=HiddenInput() doesn't work with WTF-Flask's hidden_tag()
    """


class TelInput(Input):
    input_type = 'tel'


class TelField(StringField):
    widget = TelInput()


class Form(BaseForm):
    # CsrfProtect limit
    TIME_LIMIT = 3600 * 24

    def hidden_tag_without(self, *fields):
        fields = [isinstance(f, string_types) and getattr(self, f) or f for f in fields]
        keep_fields = [f for f in self if _is_hidden(f) and f not in fields]
        return BaseForm.hidden_tag(self, *keep_fields)


def feature_flag(flag):
    def call(f, *args, **kw):
        if app.config.get(flag, False) is True:
            return f(*args, **kw)
        return abort(404)
    return decorator(call)


class Currency(object):
    def __init__(self, code, symbol):
        self.code = code
        self.symbol = symbol

CURRENCIES = [
    Currency('GBP', u'£'),
    Currency('EUR', u'€'),
]
CURRENCY_SYMBOLS = dict((c.code, c.symbol) for c in CURRENCIES)


@app.template_filter('price')
def format_price(amount, currency, after=False):
    amount = u'{0:.2f}'.format(amount)
    symbol = CURRENCY_SYMBOLS[currency]
    if after:
        return amount + symbol
    return symbol + amount


@app.template_filter('bankref')
def format_bankref(bankref):
    return '%s-%s' % (bankref[:4], bankref[4:])


@app.template_filter('gcid')
def format_gcid(gcid):
    if len(gcid) > 12:
        return 'ending %s' % gcid[-12:]
    return gcid


@app.context_processor
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


@app.context_processor
def currency_processor():
    currency = get_user_currency()
    return {'user_currency': currency}


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

import basic  # noqa
import users  # noqa
import admin  # noqa
import tickets  # noqa
import radio  # noqa
import payment  # noqa
import cfp  # noqa
import arrivals  # noqa
