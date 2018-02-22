import os
import logger
import random
import shutil

from main import create_app, db
from flask import request, _request_ctx_stack
from flask_mail import email_dispatched

if __name__ == "__main__":
    prometheus_dir = 'var/prometheus'
    os.environ['prometheus_multiproc_dir'] = prometheus_dir

    if os.path.exists(prometheus_dir):
        shutil.rmtree(prometheus_dir)
    if not os.path.exists(prometheus_dir):
        os.mkdir(prometheus_dir)

    app = create_app(dev_server=True)
    # Prevent DB connections and random numbers being shared
    ppid = os.getpid()

    @app.before_request
    def fix_shared_state():
        if os.getpid() != ppid:
            db.engine.dispose()
            random.seed()

    import prometheus_client.multiprocess

    @app.after_request
    def prometheus_cleanup(response):
        # this keeps livesum and liveall accurate
        # other metrics will hang around until restart
        prometheus_client.multiprocess.mark_process_dead(os.getpid())
        return response

    if app.config.get('DEBUG') or app.config.get('MAIL_SUPPRESS_SEND'):
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
        # Safe defaults mapped by flask.app.Flask.run
        default_host = None  # i.e. 127.0.0.1
        default_port = None  # i.e. 5000 unless specified in SERVER_NAME

    config_options = {
        'HOST': 'host',
        'PORT': 'port',
        'MAX_PROCESSES': 'processes',
        'DEV_SERVER_EVALEX': 'use_evalex',
        'DEV_SERVER_RELOAD': 'use_reloader',
        'DEV_SERVER_RELOAD_FILES': 'extra_files',
    }
    # Flask sets use_debugger, use_evalex and use_reloader when DEBUG is on.
    # We allow the debugger for nice tracebacks, but turn evalex off as it's
    # one step away from RCE.
    # NB: using the debug toolbar means lots will be leaked, including paths,
    # secrets and DB credentials, so only use it when running on localhost.
    options = {
        'host': default_host,
        'port': default_port,
        'processes': 2,
        'use_evalex': False,
        'extra_files': [os.environ.get('SETTINGS_FILE'), 'logging.yaml'],
    }
    for key, option in config_options.items():
        if key in app.config:
            options[option] = app.config[key]

    # http://werkzeug.pocoo.org/docs/latest/serving/
    app.run(**options)

