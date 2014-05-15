# encoding=utf-8
from main import app
from flask import session

from models.ticket import Ticket

from flask_wtf import Form as BaseForm
from flask_wtf.form import _is_hidden
from wtforms import (
    IntegerField, SelectField, HiddenField,
)
from wtforms.validators import Required, ValidationError
from wtforms.compat import string_types

from decorator import decorator
import time
from datetime import datetime
import iso8601

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

class Form(BaseForm):
    def hidden_tag_without(self, *fields):
        fields = [isinstance(f, string_types) and getattr(self, f) or f for f in fields]
        keep_fields = [f for f in self if _is_hidden(f) and f not in fields]
        return BaseForm.hidden_tag(self, *keep_fields)


def feature_flag(flag):
    def call(f, *args, **kw):
        if app.config.get(flag, False) == True:
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


@app.context_processor
def utility_processor():
    def format_shift_short(start, end):
        start_p, start_h = start.strftime('%p').lower(), int(start.strftime('%I'))
        end_p, end_h = end.strftime('%p').lower(), int(end.strftime('%I'))
        if start_p != end_p:
            return '%s %s-%s %s' % (start_h, start_p, end_h, end_p)
        return '%s-%s %s' % (start_h, end_h, end_p)

    def format_shift_dt(dt):
        def date_suffix(day):
            if 4 <= day <= 20 or 24 <= day <= 30:
                return '%dth' % day
            else:
                return '%d%s' % (day, ['st', 'nd', 'rd'][day % 10 - 1])
        return dt.strftime('%A %%s %H:%M') % date_suffix(dt.day)

    return dict(
        format_shift_short=format_shift_short,
        format_shift_dt=format_shift_dt,
        TICKET_CUTOFF=TICKET_CUTOFF,
        CURRENCIES=CURRENCIES,
        CURRENCY_SYMBOLS=CURRENCY_SYMBOLS,
    )

@app.context_processor
def currency_processor():
    currency = get_user_currency()
    return {'user_currency': currency}

def get_user_currency(default='GBP'):
    return session.get('currency', default)

def set_user_currency(currency):
    session['currency'] = currency

def get_basket():
    basket = []
    for code in session.get('basket', []):
        basket.append(Ticket(code=code))

    total = sum(t.type.get_price(get_user_currency()) for t in basket)

    app.logger.debug('Got basket %s with total %s', basket, total)
    return basket, total

def ticket_cutoff():
    return datetime.utcnow() > iso8601.parse_date(app.config['TICKET_CUTOFF']).replace(tzinfo=None)

TICKET_CUTOFF = ticket_cutoff()

import basic
import users
import admin
import tickets
import radio
import payment

