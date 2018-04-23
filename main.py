import time
import yaml
import logging
import logging.config

from flask import (
    Flask, url_for, render_template,
    request,
)
from flask_mail import Mail
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import MetaData
from sqlalchemy_continuum import make_versioned
from sqlalchemy_continuum.manager import VersioningManager
from sqlalchemy_continuum.plugins import FlaskPlugin
from flask_assets import Environment, Bundle
from flask_cdn import CDN
from flask_cache import Cache
from flask_debugtoolbar import DebugToolbarExtension
from flask_wtf import CsrfProtect
from loggingmanager import create_logging_manager, set_user_id
import stripe
import gocardless_pro


# If we have logging handlers set up here, don't touch them.
# This is especially problematic during testing as we don't
# want to overwrite nosetests' handlers
if len(logging.root.handlers) == 0:
    install_logging = True
    with open('logging.yaml', 'r') as f:
        conf = yaml.load(f)
        logging.config.dictConfig(conf)
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

admin_new = None
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
gocardless_client = None

assets.register('css_main', Bundle('css/main.scss',
                output='gen/main-packed.css',
                depends='css/*.scss',
                filters='pyscss,cssmin'))
assets.register('css_admin', Bundle('css/admin.scss',
                output='gen/admin-packed.css',
                depends='css/*.scss',
                filters='pyscss,cssmin'))
assets.register('css_invoice', Bundle('css/invoice.scss',
                output='gen/print-packed.css',
                depends='css/*.scss',
                filters='pyscss,cssmin'))
assets.register('css_receipt', Bundle('css/receipt.scss',
                output='gen/print-packed.css',
                depends='css/*.scss',
                filters='pyscss,cssmin'))
assets.register('css_schedule', Bundle('css/schedule.scss',
                output='gen/schedule-packed.css',
                depends='css/*.scss',
                filters='pyscss,cssmin'))
assets.register('css_arrivals', Bundle('css/arrivals.scss',
                output='gen/arrivals-packed.css',
                depends='css/*.scss',
                filters='pyscss,cssmin'))
assets.register('js_main', Bundle('js/main.js',
                output='gen/main-packed.js', filters='jsmin'))
assets.register('js_schedule', Bundle('js/schedule.js',
                output='gen/schedule-packed.js', filters='jsmin'))


def create_app(dev_server=False):
    app = Flask(__name__)
    app.config.from_envvar('SETTINGS_FILE')
    app.jinja_options['extensions'].append('jinja2.ext.do')

    if install_logging:
        create_logging_manager(app)
        # Flask has now kindly installed its own log handler which we will summarily remove.
        app.logger.propagate = 1
        app.logger.handlers = []
        if not app.debug:
            logging.root.setLevel(logging.INFO)
        else:
            logging.root.setLevel(logging.DEBUG)

    for extension in (cdn, csrf, cache, db, mail, assets, toolbar):
        extension.init_app(app)

    migrate.init_app(app, db, render_as_batch=True)

    login_manager.setup_app(app, add_context_processor=True)
    app.login_manager.login_view = 'users.login'

    from models.user import User, load_anonymous_user
    from models import site_state, feature_flag

    @login_manager.user_loader
    def load_user(userid):
        user = User.query.filter_by(id=userid).first()
        if user:
            set_user_id(user.email)
        return user

    login_manager.anonymous_user = load_anonymous_user

    if app.config.get('TICKETS_SITE'):
        global gocardless_client
        gocardless_client = gocardless_pro.Client(access_token=app.config['GOCARDLESS_ACCESS_TOKEN'],
                                                  environment=app.config['GOCARDLESS_ENVIRONMENT'])
        stripe.api_key = app.config['STRIPE_SECRET_KEY']

        @app.before_request
        def load_per_request_state():
            site_state.get_states()
            feature_flag.get_db_flags()

    if app.config.get('NO_INDEX'):
        # Prevent staging site from being displayed on Google
        @app.after_request
        def send_noindex_header(response):
            response.headers['X-Robots-Tag'] = 'noindex, nofollow'
            return response

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

    from apps.metrics import request_duration, request_total

    @app.before_request
    def before_request():
        request._start_time = time.time()

    @app.after_request
    def after_request(response):
        try:
            request_duration.labels(request.endpoint, request.method).observe(
                time.time() - request._start_time)
        except AttributeError:
            # In some cases this isn't present?
            logging.exception("Request without _start_time")
        request_total.labels(request.endpoint, request.method, response.status_code).inc()
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
    from apps.metrics import metrics
    from apps.users import users
    from apps.tickets import tickets
    from apps.payments import payments
    from apps.cfp import cfp
    from apps.cfp_review import cfp_review
    from apps.schedule import schedule
    from apps.arrivals import arrivals
    app.register_blueprint(base)
    app.register_blueprint(users)
    app.register_blueprint(metrics)
    app.register_blueprint(tickets)
    app.register_blueprint(payments)
    app.register_blueprint(cfp)
    app.register_blueprint(cfp_review, url_prefix='/cfp-review')
    app.register_blueprint(schedule)
    app.register_blueprint(arrivals, url_prefix='/arrivals')


    from flask_admin import Admin

    if app.config.get('VOLUNTEERS'):
        app.logger.info("Set up volunteers")

        from apps.volunteers.base import VolunteerIndexView
        global volunteers
        # Use the flask-admin system to run the volunteer stuff
        # This is all pretty janky to account cope with imports & using flask
        # admin for this and admin_new but separately.
        volunteers = Admin(url='/volunteers', name='EMF Volunteers',
                           template_mode='bootstrap3',
                           index_view=VolunteerIndexView(url='/volunteers'),
                           base_template='volunteers/base.html')

        volunteers.endpoint = 'volunteers'
        volunteers.endpoint_prefix = 'volunteers'
        volunteers.init_app(app)

        from apps.volunteers import init
        init()

    global admin_new
    from apps.common.flask_admin_base import AppAdminIndexView
    admin_new = Admin(url='/admin/new', name='EMF Admin', template_mode='bootstrap3',
                      index_view=AppAdminIndexView(url='/admin/new'),
                      base_template='flask-admin-base.html')

    admin_new.endpoint_prefix = 'admin_new'

    from apps.admin import admin
    app.register_blueprint(admin, url_prefix='/admin')

    admin_new.init_app(app)

    return app


def external_url(endpoint, **values):
    """ Generate an absolute external URL. If you need to override this,
        you're probably doing something wrong. """
    return url_for(endpoint, _external=True, **values)
