# encoding=utf-8
from flask import Flask, session, _request_ctx_stack
from flaskext.login import LoginManager
from flaskext.mail import Mail
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.orm.exc import NoResultFound
from flask.ext.assets import Environment, Bundle

import logging
import time

logging.basicConfig(level=logging.NOTSET)

app = Flask(__name__)
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

@app.context_processor
def utility_processor():
    def format_price(amount, currency=None, after=False):
        if currency is None:
            currency = CURRENCY_SYMBOLS[session.get('currency', 'GBP')]

        amount = u'{0:.2f}'.format(amount)
        if after:
            return amount + currency
        return currency + amount

    def format_ticket_price(ticket_type):
        currency = session.get('currency', 'GBP')
        ticket_price = ticket_type.get_price(currency)
        symbol = CURRENCY_SYMBOLS[currency]
        return format_price(ticket_price, symbol)

    def format_bankref(bankref):
        return '%s-%s' % (bankref[:4], bankref[4:])

    def isoformat_utc(dt, sep='T'):
        return time.strftime('%Y-%m-%d' + sep + '%H:%M:%SZ', dt.utctimetuple())
        
    return dict(
        format_price=format_price,
        format_ticket_price=format_ticket_price,
        format_bankref=format_bankref,
        isoformat_utc=isoformat_utc,
    )

@app.context_processor
def currency_processor():
    currency = session.get('currency', 'GBP')
    return {'user_currency': currency,
            'user_currency_symbol': CURRENCY_SYMBOLS[currency]}

db = SQLAlchemy(app)

mail = Mail(app)

assets = Environment(app)
css = Bundle('css/bootstrap.css',
                'css/bootstrap-responsive.css', 
                'css/main.css',
                output='gen/packed.css', filters='cssmin')
assets.register('css_all', css)

js = Bundle('js/jquery-1.7.2.js', 'js/bootstrap.js', output='gen/packed.js', 
                filters='rjsmin')
assets.register('js_all', js)


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
