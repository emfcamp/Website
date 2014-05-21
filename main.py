from flask import Flask
from flaskext.mail import Mail
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
css = Bundle('css/main.css',
                output='gen/packed.css', filters='cssmin')
assets.register('css_all', css)

gocardless.environment = app.config['GOCARDLESS_ENVIRONMENT']
gocardless.set_details(app_id=app.config['GOCARDLESS_APP_ID'],
                        app_secret=app.config['GOCARDLESS_APP_SECRET'],
                        access_token=app.config['GOCARDLESS_ACCESS_TOKEN'],
                        merchant_id=app.config['GOCARDLESS_MERCHANT_ID'])

stripe.api_key = app.config['STRIPE_SECRET_KEY']

from views import *
from models import *

if __name__ == "__main__":
    if app.config.get('DEBUG'):
        db.create_all()

    if app.config.get('FIX_URL_SCHEME'):
        from flask import request, _request_ctx_stack
        @app.before_request
        def fix_url_scheme():
            request.environ['wsgi.url_scheme'] = 'https'
            _request_ctx_stack.top.url_adapter.url_scheme = 'https'

    app.run()
