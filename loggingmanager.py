""" A middleware to export user IDs for logging.

    Werkzeug logs the request after the Flask app context has ended
    so we use Werkzeug's Local object to pass the user ID into the
    logging formatter.
"""

import logging
from werkzeug.local import Local, LocalManager

local = Local()
local_manager = LocalManager([local])


class ContextFormatter(logging.Formatter):
    """ A logging formatter which inserts the user ID
        into the logging record. """
    def format(self, record):
        record.user = getattr(local, 'user_id', None)
        return logging.Formatter.format(self, record)


def set_user_id(uid):
    """ Set the user ID for later use in logging. """
    local.user_id = uid


def create_logging_manager(app):
    app.wsgi_app = local_manager.make_middleware(app.wsgi_app)
