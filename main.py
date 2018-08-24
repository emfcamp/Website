import time
import yaml
import logging
import logging.config

from flask import (
    Flask, url_for, render_template,
    request,
)
from flask_mail import Mail, email_dispatched
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import MetaData
from sqlalchemy_continuum import make_versioned
from sqlalchemy_continuum.manager import VersioningManager
from sqlalchemy_continuum.plugins import FlaskPlugin
from flask_assets import Environment, Bundle
from webassets.filter import get_filter
from flask_cdn import CDN
from flask_cache import Cache
from flask_debugtoolbar import DebugToolbarExtension
from flask_wtf import CsrfProtect
from flask_cors import CORS
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

def include_object(object, name, type_, reflected, compare_to):
    if (type_, name, reflected) == ('table', 'spatial_ref_sys', True):
        return False

    return True


cache = Cache()
csrf = CsrfProtect()
migrate = Migrate(include_object=include_object)
manager = VersioningManager(options={'strategy': 'subquery'})
make_versioned(manager=manager, plugins=[FlaskPlugin()])
mail = Mail()
cdn = CDN()
login_manager = LoginManager()
assets = Environment()
toolbar = DebugToolbarExtension()
gocardless_client = None
volunteer_admin = None


pyscss = get_filter('pyscss', style='compressed')
assets.register('css_main', Bundle('css/main.scss',
                output='gen/main-packed.css',
                depends='css/*.scss',
                filters=pyscss))
assets.register('css_admin', Bundle('css/admin.scss',
                output='gen/admin-packed.css',
                depends='css/*.scss',
                filters=pyscss))
assets.register('css_volunteer', Bundle('css/volunteer.scss',
                output='gen/volunteer-packed.css',
                depends='css/*.scss',
                filters=pyscss))
assets.register('css_invoice', Bundle('css/invoice.scss',
                output='gen/invoice-packed.css',
                depends='css/*.scss',
                filters=pyscss))
assets.register('css_receipt', Bundle('css/receipt.scss',
                output='gen/receipt-packed.css',
                depends='css/*.scss',
                filters=pyscss))
assets.register('css_schedule', Bundle('css/schedule.scss',
                output='gen/schedule-packed.css',
                depends='css/*.scss',
                filters=pyscss))
assets.register('css_arrivals', Bundle('css/arrivals.scss',
                output='gen/arrivals-packed.css',
                depends='css/*.scss',
                filters=pyscss))
assets.register('js_main', Bundle('js/main.js', 'js/line-up.js',
                output='gen/main-packed.js', filters='jsmin'))
assets.register('js_schedule', Bundle('js/schedule.js',
                output='gen/schedule-packed.js', filters='jsmin'))
assets.register('js_volunteer_schedule', Bundle('js/volunteer-schedule.js',
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

    from apps.metrics import request_duration, request_total

    # Must be run before crsf.init_app
    @app.before_request
    def before_request():
        request._start_time = time.time()

    @app.after_request
    def after_request(response):
        try:
            request_duration.labels(request.endpoint, request.method).observe(
                time.time() - request._start_time)
        except AttributeError:
            logging.exception("Request without _start_time - check app.before_request ordering")
        request_total.labels(request.endpoint, request.method, response.status_code).inc()
        return response

    for extension in (cdn, csrf, cache, db, mail, assets, toolbar):
        extension.init_app(app)

    def log_email(message, app):
        app.logger.info("Emailing %s: %r", message.recipients, message.subject)

    email_dispatched.connect(log_email)

    cors_origins = ['https://map.emfcamp.org', 'https://wiki.emfcamp.org']
    if app.config.get('DEBUG'):
        cors_origins = ['http://localhost:8080', 'https://maputnik.github.io']
    CORS(app, resources={r"/api/*": {"origins": cors_origins}},
        supports_credentials=True)

    migrate.init_app(app, db)

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

    @app.errorhandler(404)
    def handle_404(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def handle_500(e):
        return render_template('errors/500.html'), 500

    @app.shell_context_processor
    def shell_imports():
        ctx = {}

        # Import models and constants
        import models
        for attr in dir(models):
            if attr[0].isupper():
                ctx[attr] = getattr(models, attr)

        # And just for convenience
        ctx['db'] = db

        return ctx

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
    from apps.api import api_bp
    app.register_blueprint(base)
    app.register_blueprint(users)
    app.register_blueprint(metrics)
    app.register_blueprint(tickets)
    app.register_blueprint(payments)
    app.register_blueprint(cfp)
    app.register_blueprint(cfp_review, url_prefix='/cfp-review')
    app.register_blueprint(schedule)
    app.register_blueprint(arrivals, url_prefix='/arrivals')
    app.register_blueprint(api_bp, url_prefix='/api')

    if app.config.get('VOLUNTEERS'):
        from apps.volunteer import volunteer
        app.register_blueprint(volunteer, url_prefix='/volunteer')

        from flask_admin import Admin
        from apps.volunteer.flask_admin_base import VolunteerAdminIndexView

        global volunteer_admin
        volunteer_admin = Admin(url='/volunteer/admin', name='EMF Volunteers',
                                template_mode='bootstrap3',
                                index_view=VolunteerAdminIndexView(url='/volunteer/admin'),
                                base_template='volunteer/admin/flask-admin-base.html')
        volunteer_admin.endpoint_prefix = 'volunteer_admin'
        volunteer_admin.init_app(app)

        import apps.volunteer.admin  # noqa: F401

    from apps.admin import admin
    app.register_blueprint(admin, url_prefix='/admin')

    return app


def external_url(endpoint, **values):
    """ Generate an absolute external URL. If you need to override this,
        you're probably doing something wrong. """
    return url_for(endpoint, _external=True, **values)
