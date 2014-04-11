# encoding=utf-8
from flask import Flask, session, _request_ctx_stack
from flaskext.mail import Mail
from flask.ext.login import LoginManager
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.assets import Environment, Bundle
from flask_wtf import CsrfProtect

from datetime import datetime
import iso8601
import logging
import time

logging.basicConfig(level=logging.NOTSET)

app = Flask(__name__)
CsrfProtect(app)
app.config.from_envvar('SETTINGS_FILE')

login_manager = LoginManager()
login_manager.setup_app(app, add_context_processor=True)
app.login_manager.login_view = 'login'

CURRENCY_SYMBOLS = {'GBP': u'£', 'EUR': u'€'}

class ContextFormatter(logging.Formatter):
    def format(self, record):
        try:
            record.user = _request_ctx_stack.top.user.email
        except AttributeError:
            record.user = 'None'
        return logging.Formatter.format(self, record)

fmt = ContextFormatter('%(levelname)s:%(user)s:%(name)s:%(message)s')
hdlr = logging.StreamHandler()
hdlr.setFormatter(fmt)
app.logger.addHandler(hdlr)
app.logger.propagate = False

def get_user_currency(default='GBP'):
    if not app.config.get('ENABLE_EURO'):
        return default
    return session.get('currency', default)

def set_user_currency(currency):
    session['currency'] = currency

def ticket_cutoff():
    return datetime.utcnow() > iso8601.parse_date(app.config['TICKET_CUTOFF']).replace(tzinfo=None)


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
        ticket_cutoff=ticket_cutoff
    )

@app.context_processor
def currency_processor():
    currency = get_user_currency()
    return {'user_currency': currency,
            'user_currency_symbol': CURRENCY_SYMBOLS[currency]}

db = SQLAlchemy(app)

mail = Mail(app)

assets = Environment(app)
css = Bundle('css/main.css',
                output='gen/packed.css', filters='cssmin')
assets.register('css_all', css)
import gocardless

gocardless.environment = app.config['GOCARDLESS_ENVIRONMENT']
gocardless.set_details(app_id=app.config['GOCARDLESS_APP_ID'],
                        app_secret=app.config['GOCARDLESS_APP_SECRET'],
                        access_token=app.config['GOCARDLESS_ACCESS_TOKEN'],
                        merchant_id=app.config['GOCARDLESS_MERCHANT_ID'])

from views import *
from models import *
db.create_all()

@login_manager.user_loader
def load_user(userid):
    return User.query.filter_by(id=userid).first()

if __name__ == "__main__":
    app.run()
