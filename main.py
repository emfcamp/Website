import os
import logging
import logger

from flask import Flask, request, _request_ctx_stack, url_for
from flask_mail import Mail, email_dispatched
from flask.ext.login import LoginManager
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.assets import Environment, Bundle
from flask_wtf import CsrfProtect
import gocardless
import stripe

# If we have logging handlers set up here, don't touch them.
# This is especially problematic during testing as we don't
# want to overwrite nosetests' handlers
if len(logging.root.handlers) == 0:
    install_logging = True
    logging.basicConfig(level=logging.NOTSET)
else:
    install_logging = False


csrf = CsrfProtect()
db = SQLAlchemy()
mail = Mail()
login_manager = LoginManager()
assets = Environment()

assets.register('css_main', Bundle('css/main.css',
                output='gen/main-packed.css', filters='cssmin'))
assets.register('css_admin', Bundle('css/admin.css',
                output='gen/admin-packed.css', filters='cssmin'))
assets.register('css_print', Bundle('css/print.css',
                output='gen/print-packed.css', filters='cssmin'))
assets.register('css_arrivals', Bundle('css/arrivals.css',
                output='gen/arrivals-packed.css', filters='cssmin'))
assets.register('js_main', Bundle('js/main.js',
                output='gen/main-packed.js', filters='jsmin'))


def create_app():
    app = Flask(__name__)
    app.config.from_envvar('SETTINGS_FILE')

    if install_logging:
        logger.setup_logging(app)

    csrf.init_app(app)
    db.init_app(app)
    mail.init_app(app)
    assets.init_app(app)
    login_manager.setup_app(app, add_context_processor=True)
    app.login_manager.login_view = 'users.login'

    from models.user import User

    @login_manager.user_loader
    def load_user(userid):
        user = User.query.filter_by(id=userid).first()
        if user:
            _request_ctx_stack.top.user_email = user.email
        return user

    if app.config.get('TICKETS_SITE'):
        gocardless.environment = app.config['GOCARDLESS_ENVIRONMENT']
        gocardless.set_details(app_id=app.config['GOCARDLESS_APP_ID'],
                               app_secret=app.config['GOCARDLESS_APP_SECRET'],
                               access_token=app.config['GOCARDLESS_ACCESS_TOKEN'],
                               merchant_id=app.config['GOCARDLESS_MERCHANT_ID'])

        stripe.api_key = app.config['STRIPE_SECRET_KEY']

    from apps.common import load_utility_functions
    load_utility_functions(app)

    from apps.base import base
    from apps.users import users
    from apps.tickets import tickets
    from apps.payments import payments
    from apps.cfp import cfp
    from apps.admin import admin
    app.register_blueprint(base)
    app.register_blueprint(users)
    app.register_blueprint(tickets)
    app.register_blueprint(payments)
    app.register_blueprint(cfp)
    app.register_blueprint(admin, url_prefix='/admin')

    return app


def external_url(endpoint, **values):
    """ Generate an absolute external URL. If you need to override this,
        you're probably doing something wrong. """
    return url_for(endpoint, _external=True, **values)


if __name__ == "__main__":
    app = create_app()
    if app.config.get('DEBUG'):
        with app.app_context():
            db.create_all()
        email_dispatched.connect(logger.mail_logging)

    if app.config.get('FIX_URL_SCHEME'):
        # The Flask debug server doesn't process _FORWARDED_ headers,
        # so there's no other way to set the wsgi.url_scheme.
        # Consider using an actual WSGI host (perhaps with ProxyFix) instead.

        @app.before_request
        def fix_url_scheme():
            if request.environ.get('HTTP_X_FORWARDED_PROTO') == 'https':
                request.environ['wsgi.url_scheme'] = 'https'
                _request_ctx_stack.top.url_adapter.url_scheme = 'https'

    if os.path.exists('.inside-vagrant'):
        # Make it easier to access from host machine
        default_host = '0.0.0.0'
        default_port = 5000
    else:
        # Safe defaults
        default_host = None  # i.e. localhost
        default_port = None  # i.e. 5000

    host = app.config.get('HOST', default_host)
    port = app.config.get('PORT', default_port)
    app.run(processes=2, host=host, port=port)
