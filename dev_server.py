import os
import logger
import random
import shutil

from main import create_app, db
from flask import request, _request_ctx_stack
from flask_mail import email_dispatched


prometheus_dir = "var/prometheus"
os.environ["prometheus_multiproc_dir"] = prometheus_dir

if os.path.exists(prometheus_dir):
    shutil.rmtree(prometheus_dir, True)
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


import prometheus_client.multiprocess  # noqa


@app.after_request
def prometheus_cleanup(response):
    # this keeps livesum and liveall accurate
    # other metrics will hang around until restart
    prometheus_client.multiprocess.mark_process_dead(os.getpid())
    return response


if app.config.get("DEBUG") or app.config.get("MAIL_SUPPRESS_SEND"):
    email_dispatched.connect(logger.mail_logging)

if app.config.get("FIX_URL_SCHEME"):
    # The Flask debug server doesn't process _FORWARDED_ headers,
    # so there's no other way to set the wsgi.url_scheme.
    # Consider using an actual WSGI host (perhaps with ProxyFix) instead.

    @app.before_request
    def fix_url_scheme():
        if request.environ.get("HTTP_X_FORWARDED_PROTO") == "https":
            request.environ["wsgi.url_scheme"] = "https"
            _request_ctx_stack.top.url_adapter.url_scheme = "https"
