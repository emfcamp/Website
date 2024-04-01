import time
import yaml
import secrets
import logging
import logging.config
from pathlib import Path

from flask import Flask, url_for, render_template, request, g
from flask_mailman import Mail
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import MetaData
from sqlalchemy_continuum import make_versioned
from sqlalchemy_continuum.manager import VersioningManager
from sqlalchemy_continuum.plugins import FlaskPlugin
from flask_static_digest import FlaskStaticDigest
from flask_caching import Cache
from flask_debugtoolbar import DebugToolbarExtension
from flask_cors import CORS
from loggingmanager import create_logging_manager, set_user_id
from werkzeug.exceptions import HTTPException
import stripe
import pywisetransfer


# If we have logging handlers set up here, don't touch them.
# This is especially problematic during testing as we don't
# want to overwrite nosetests' handlers. Note: if anything
# logs before this point, logging.basicConfig will install
# a default stderr StreamHandler.
if len(logging.root.handlers) == 0:
    install_logging = True
    with open("logging.yaml", "r") as f:
        conf = yaml.load(f, Loader=yaml.FullLoader)
        if Path("logging.override.yaml").is_file():
            with open("logging.override.yaml", "r") as fo:
                conf_overrides = yaml.load(fo, Loader=yaml.FullLoader)

                def update_logging(d, s):
                    for k, v in s.items():
                        if isinstance(v, dict):
                            d[k] = update_logging(d.get(k, {}), v)
                        elif v is not None:
                            d[k] = v
                    return d

                update_logging(conf, conf_overrides)

        logging.config.dictConfig(conf)

else:
    install_logging = False

naming_convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))


def include_object(object, name, type_, reflected, compare_to):
    if (type_, name, reflected) == ("table", "spatial_ref_sys", True):
        return False

    return True


cache = Cache()
migrate = Migrate(include_object=include_object)
manager = VersioningManager(options={"strategy": "subquery"})
make_versioned(manager=manager, plugins=[FlaskPlugin()])
mail = Mail()
login_manager = LoginManager()
static_digest = FlaskStaticDigest()
toolbar = DebugToolbarExtension()
wise = None


def check_cache_configuration():
    """Check the cache configuration is appropriate for production"""
    if cache.cache.__class__.__name__ == "SimpleCache":
        # SimpleCache is per-process, not appropriate for prod
        logging.warning(
            "Per-process cache being used outside dev server - refreshing will not work"
        )

    TEST_CACHE_KEY = "emf_test_cache_key"
    cache.set(TEST_CACHE_KEY, "exists")
    if cache.get(TEST_CACHE_KEY) != "exists":
        logging.warning(
            "Flask-Caching backend does not appear to be working. Performance may be affected."
        )


def create_app(dev_server=False, config_override=None):
    app = Flask(__name__)
    app.config.from_envvar("SETTINGS_FILE")
    if config_override:
        app.config.from_mapping(config_override)
    app.jinja_env.add_extension("jinja2.ext.do")

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
                time.time() - request._start_time
            )
        except AttributeError:
            logging.exception(
                "Request without _start_time - check app.before_request ordering"
            )
        request_total.labels(
            request.endpoint, request.method, response.status_code
        ).inc()
        return response

    for extension in (cache, db, mail, static_digest, toolbar):
        extension.init_app(app)

    cors_origins = ["https://map.emfcamp.org", "https://wiki.emfcamp.org"]
    if app.config.get("DEBUG"):
        cors_origins = ["http://localhost:8080", "https://maputnik.github.io"]

    # NOTE: static files are served by nginx in production, so CORS headers must also be set there.
    CORS(
        app,
        resources={
            r"/api/*": {"origins": cors_origins},
            r"/static/*": {"origins": cors_origins},
        },
        supports_credentials=True,
    )

    migrate.init_app(app, db)

    login_manager.init_app(app, add_context_processor=True)
    app.login_manager.login_view = "users.login"

    from models.user import User, load_anonymous_user
    from models import site_state, feature_flag

    @login_manager.user_loader
    def load_user(userid):
        user = User.query.filter_by(id=userid).first()
        if user:
            set_user_id(user.email)
        return user

    login_manager.anonymous_user = load_anonymous_user

    stripe.api_key = app.config["STRIPE_SECRET_KEY"]
    global wise
    wise = pywisetransfer.Client(
        api_key=app.config["TRANSFERWISE_API_TOKEN"],
        environment=app.config["TRANSFERWISE_ENVIRONMENT"],
        private_key_file=app.config.get("TRANSFERWISE_PRIVATE_KEY_FILE"),
    )

    @app.before_request
    def load_per_request_state():
        site_state.get_states()
        feature_flag.get_db_flags()

    if app.config.get("NO_INDEX"):
        # Prevent staging site from being displayed on Google
        @app.after_request
        def send_noindex_header(response):
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
            return response

    @app.context_processor
    def add_csp_nonce():
        g.csp_nonce = secrets.token_urlsafe(16)
        return {"csp_nonce": g.csp_nonce}

    @app.after_request
    def send_security_headers(response):
        use_hsts = app.config.get("HSTS", False)
        if use_hsts:
            max_age = app.config.get("HSTS_MAX_AGE", 3600 * 24 * 30 * 6)
            response.headers["Strict-Transport-Security"] = "max-age=%s" % max_age

        response.headers["X-Frame-Options"] = "deny"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"

        csp = {
            # unsafe-eval is required by the dhtmlx scheduler on the admin interface currently.
            "script-src": ["'self'", "https://js.stripe.com", "'unsafe-eval'"],
            "style-src": ["'self'", "'unsafe-inline'"],
            # Note: the below is more strict as it only allows inline styles in style=
            # attributes, however it's unsupported by Safari at this time...
            #  "style-src-attr": ["'unsafe-inline'"],
            "font-src": ["'self'", "https://fonts.gstatic.com"],
            "frame-src": [
                "https://js.stripe.com/",
                "https://media.ccc.de",
                "https://www.youtube.com",
                "https://archive.org",
            ],
        }

        # Fixups for flask-admin which includes lots of nasty inline JS
        csp["script-src"] += [
            "'sha256-Jxve8bBSodQplIZw4Y1walBJ0hFTx8sZ5xr+Pjr/78Y='",  # Edit record
            "'sha256-XOlW2U5UiDeV2S/HgKqbp++Fo1I5uiUT2thFRUeFW/g='",  # View record
            "'unsafe-hashes'",
            "'sha256-2rvfFrggTCtyF5WOiTri1gDS8Boibj4Njn0e+VCBmDI='",  # return false;
            "'sha256-gC0PN/M+TSxp9oNdolzpqpAA+ZRrv9qe1EnAbUuDmk8='",  # return modelActions.execute('notify');
        ]

        if app.config.get("DEBUG_TB_ENABLED"):
            # This hash is for the flask debug toolbar. It may break once they upgrade it.
            csp["script-src"].append(
                "'sha256-zWl5GfUhAzM8qz2mveQVnvu/VPnCS6QL7Niu6uLmoWU='"
            )

        if "csp_nonce" in g:
            csp["script-src"].append(f"'nonce-{g.csp_nonce}'")

        value = "; ".join(k + " " + " ".join(v) for k, v in csp.items())

        if app.config.get("DEBUG"):
            response.headers["Content-Security-Policy"] = value
        else:
            response.headers["Content-Security-Policy-Report-Only"] = (
                value + "; report-uri https://emfcamp.report-uri.com/r/d/csp/reportOnly"
            )
            response.headers[
                "Report-To"
            ] = '{"group":"default","max_age":31536000,"endpoints":[{"url":"https://emfcamp.report-uri.com/a/d/g"}],"include_subdomains":false}'

            # Disable Network Error Logging.
            # This doesn't seem to be very useful and it's using up our report-uri quota.
            response.headers["NEL"] = '{"max_age":0}'
        return response

    if not app.debug:
        check_cache_configuration()

        @app.errorhandler(Exception)
        def handle_exception(e):
            """Generic exception handler to catch and log unhandled exceptions in production."""
            if isinstance(e, HTTPException):
                # HTTPException is used to implement flask's HTTP errors so pass it through.
                return e

            app.logger.exception("Unhandled exception in request: %s", request)
            return render_template("errors/500.html"), 500

    @app.errorhandler(404)
    def handle_404(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def handle_500(e):
        return render_template("errors/500.html"), 500

    @app.shell_context_processor
    def shell_imports():
        ctx = {}

        # Import models and constants
        import models

        for attr in dir(models):
            if attr[0].isupper():
                ctx[attr] = getattr(models, attr)

        # And just for convenience
        ctx["db"] = db

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
    from apps.villages import villages
    from apps.admin import admin
    from apps.volunteer import volunteer
    from apps.volunteer.admin import volunteer_admin
    from apps.volunteer.admin.notify import notify
    from apps.notifications import notifications

    app.register_blueprint(base)
    app.register_blueprint(users)
    app.register_blueprint(metrics)
    app.register_blueprint(tickets)
    app.register_blueprint(payments)
    app.register_blueprint(cfp)
    app.register_blueprint(cfp_review, url_prefix="/cfp-review")
    app.register_blueprint(schedule)
    app.register_blueprint(arrivals, url_prefix="/arrivals")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(villages, url_prefix="/villages")
    app.register_blueprint(admin, url_prefix="/admin")
    app.register_blueprint(volunteer, url_prefix="/volunteer")
    app.register_blueprint(notify, url_prefix="/volunteer/admin/notify")
    app.register_blueprint(notifications, url_prefix="/account/notifications")

    volunteer_admin.init_app(app)

    return app


def external_url(endpoint, **values):
    """Generate an absolute external URL. If you need to override this,
    you're probably doing something wrong.
    """
    return url_for(endpoint, _external=True, **values)
