import logging
import logger
import random
import os

from flask import Flask, _request_ctx_stack, url_for, render_template
from flask_mail import Mail
from flask.ext.login import LoginManager
from flask.ext.sqlalchemy import SQLAlchemy
from flask.ext.migrate import Migrate
from sqlalchemy import MetaData
from sqlalchemy_continuum import make_versioned
from sqlalchemy_continuum.manager import VersioningManager
from sqlalchemy_continuum.plugins import FlaskPlugin
from flask.ext.assets import Environment, Bundle
from flask.ext.cdn import CDN
from flask.ext.cache import Cache
from flask_debugtoolbar import DebugToolbarExtension
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

naming_convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}
db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))

cache = Cache()
csrf = CsrfProtect()
migrate = Migrate()
manager = VersioningManager(options={'strategy': 'subquery'})
make_versioned(manager=manager, plugins=[FlaskPlugin()])
mail = Mail()
cdn = CDN()
login_manager = LoginManager()
assets = Environment()
toolbar = DebugToolbarExtension()

assets.register('css_main', Bundle('css/main.scss',
                output='gen/main-packed.css',
                depends='css/*.scss',
                filters='pyscss,cssmin'))
assets.register('css_admin', Bundle('css/admin.scss',
                output='gen/admin-packed.css',
                depends='css/*.scss',
                filters='pyscss,cssmin'))
assets.register('css_print', Bundle('css/print.scss',
                output='gen/print-packed.css',
                depends='css/*.scss',
                filters='pyscss,cssmin'))
assets.register('css_arrivals', Bundle('css/arrivals.scss',
                output='gen/arrivals-packed.css',
                depends='css/*.scss',
                filters='pyscss,cssmin'))
assets.register('js_main', Bundle('js/main.js',
                output='gen/main-packed.js', filters='jsmin'))


def create_app(dev_server=False):
    app = Flask(__name__)
    app.config.from_envvar('SETTINGS_FILE')
    app.jinja_options['extensions'].append('jinja2.ext.do')

    if install_logging:
        logger.setup_logging(app)

    for extension in (cdn, csrf, cache, db, mail, assets, toolbar):
        extension.init_app(app)

    migrate.init_app(app, db, render_as_batch=True)

    login_manager.setup_app(app, add_context_processor=True)
    app.login_manager.login_view = 'users.login'

    from models.user import User
    from models import site_state, feature_flag

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

        @app.before_request
        def load_per_request_state():
            site_state.get_states()
            feature_flag.get_db_flags()

    if app.config.get('DEBUG'):
        # Prevent staging site from being displayed on Google
        @app.after_request
        def send_noindex_header(response):
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
            return response

        # Prevent DB connections and random numbers being shared
        ppid = os.getpid()
        @app.before_request
        def fix_shared_state():
            if os.getpid() != ppid:
                db.engine.dispose()
                random.seed()

    @app.before_request
    def simple_cache_warning():
        if not dev_server and app.config.get('CACHE_TYPE', 'null') == 'simple':
            logging.warn('Per-process cache being used outside dev server - refreshing will not work')

    @app.after_request
    def send_security_headers(response):
        use_hsts = app.config.get('HSTS', False)
        if use_hsts:
            max_age = app.config.get('HSTS_MAX_AGE', 3600 * 24 * 7 * 4)
            response.headers['Strict-Transport-Security'] = 'max-age=%s' % max_age

        response.headers['X-Frame-Options'] = 'deny'
        response.headers['X-Content-Type-Options'] = 'nosniff'

        return response

    @app.errorhandler(404)
    def handle_404(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def handle_500(e):
        return render_template('errors/500.html'), 500

    from apps.common import load_utility_functions
    load_utility_functions(app)

    from apps.base import base
    from apps.users import users
    from apps.tickets import tickets
    from apps.payments import payments
    from apps.cfp import cfp
    from apps.cfp_review import cfp_review
    from apps.schedule import schedule
    from apps.arrivals import arrivals
    from apps.admin import admin
    app.register_blueprint(base)
    app.register_blueprint(users)
    app.register_blueprint(tickets)
    app.register_blueprint(payments)
    app.register_blueprint(cfp)
    app.register_blueprint(cfp_review, url_prefix='/cfp-review')
    app.register_blueprint(schedule)
    app.register_blueprint(arrivals, url_prefix='/arrivals')
    app.register_blueprint(admin, url_prefix='/admin')

    return app


def external_url(endpoint, **values):
    """ Generate an absolute external URL. If you need to override this,
        you're probably doing something wrong. """
    return url_for(endpoint, _external=True, **values)
