from flask import Flask
from flask import url_for
from flask_mail import Mail, email_dispatched
from flask.ext.login import LoginManager
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.assets import Environment, Bundle
from flask_wtf import CsrfProtect

import gocardless
import stripe

import logging
import logger

logging.basicConfig(level=logging.NOTSET)

app = Flask(__name__)
csrf = CsrfProtect(app)
app.config.from_envvar('SETTINGS_FILE')

logger.setup_logging(app)

db = SQLAlchemy(app)
mail = Mail(app)
login_manager = LoginManager()

assets = Environment(app)
css_all = Bundle('css/main.css',
                  output='gen/packed.css', filters='cssmin')
css_admin = Bundle('css/admin.css',
                   output='gen/admin-packed.css', filters='cssmin')
css_print = Bundle('css/print.css',
                   output='gen/print-packed.css', filters='cssmin')
css_arrivals = Bundle('css/arrivals.css',
                      output='gen/arrivals-packed.css', filters='cssmin')

assets.register('css_all', css_all)
assets.register('css_admin', css_admin)
assets.register('css_print', css_print)
assets.register('css_arrivals', css_arrivals)

if app.config.get('TICKETS_SITE'):
    gocardless.environment = app.config['GOCARDLESS_ENVIRONMENT']
    gocardless.set_details(app_id=app.config['GOCARDLESS_APP_ID'],
                            app_secret=app.config['GOCARDLESS_APP_SECRET'],
                            access_token=app.config['GOCARDLESS_ACCESS_TOKEN'],
                            merchant_id=app.config['GOCARDLESS_MERCHANT_ID'])

    stripe.api_key = app.config['STRIPE_SECRET_KEY']


def external_url(endpoint, **values):
    """ Generate an absolute external URL. If you need to override this,
        you're probably doing something wrong. """
    return url_for(endpoint, _external=True, **values)

from views import *
from models import *

if __name__ == "__main__":
    if app.config.get('DEBUG'):
        db.create_all()
        email_dispatched.connect(logger.mail_logging)

    if app.config.get('FIX_URL_SCHEME'):
        # The Flask debug server doesn't process _FORWARDED_ headers,
        # so there's no other way to set the wsgi.url_scheme.
        # Consider using an actual WSGI host (perhaps with ProxyFix) instead.
        from flask import request, _request_ctx_stack
        @app.before_request
        def fix_url_scheme():
            if request.environ.get('HTTP_X_FORWARDED_PROTO') == 'https':
                request.environ['wsgi.url_scheme'] = 'https'
                _request_ctx_stack.top.url_adapter.url_scheme = 'https'

    app.run(processes=2)
