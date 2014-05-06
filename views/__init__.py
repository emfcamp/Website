# encoding=utf-8
from main import app
from flask import session

from decorator import decorator
import time
from datetime import datetime
import iso8601

def feature_flag(flag):
    def call(f, *args, **kw):
        if app.config.get(flag, False) == True:
            return f(*args, **kw)
        return abort(404)
    return decorator(call)

@app.context_processor
def utility_processor():
    def format_price(amount, currency=None, after=False):
        if currency is None:
            currency = CURRENCY_SYMBOLS[get_user_currency()]

        amount = u'{0:.2f}'.format(amount)
        if after:
            return amount + currency
        return currency + amount

    def format_ticket_price(ticket_type):
        currency = get_user_currency()
        ticket_price = ticket_type.get_price(currency)
        symbol = CURRENCY_SYMBOLS[currency]
        return format_price(ticket_price, symbol)

    def format_bankref(bankref):
        return '%s-%s' % (bankref[:4], bankref[4:])

    def isoformat_utc(dt, sep='T'):
        return time.strftime('%Y-%m-%d' + sep + '%H:%M:%SZ', dt.utctimetuple())

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
        format_price=format_price,
        format_ticket_price=format_ticket_price,
        format_bankref=format_bankref,
        isoformat_utc=isoformat_utc,
        format_shift_short=format_shift_short,
        format_shift_dt=format_shift_dt,
        TICKET_CUTOFF=TICKET_CUTOFF
    )

CURRENCY_SYMBOLS = {'GBP': u'£', 'EUR': u'€'}

@app.context_processor
def currency_processor():
    currency = get_user_currency()
    return {'user_currency': currency,
            'user_currency_symbol': CURRENCY_SYMBOLS[currency]}

def get_user_currency(default='GBP'):
    return session.get('currency', default)

def set_user_currency(currency):
    session['currency'] = currency

def ticket_cutoff():
    return datetime.utcnow() > iso8601.parse_date(app.config['TICKET_CUTOFF']).replace(tzinfo=None)

TICKET_CUTOFF = ticket_cutoff()

import basic
import users
import admin
import tickets
import radio
import payment

