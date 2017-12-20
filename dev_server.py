import os
import logger
from main import create_app
from flask import request, _request_ctx_stack
from flask_mail import email_dispatched

if __name__ == "__main__":
    app = create_app(dev_server=True)
    if app.config.get('DEBUG'):
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
