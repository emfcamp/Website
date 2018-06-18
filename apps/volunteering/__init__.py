from flask import (
    Blueprint, redirect, url_for, current_app as app,
)
from flask_login import current_user


volunteering = Blueprint('volunteering', __name__)

@volunteering.route('/')
def home():
    app.logger.info('Here I am')

    if current_user.has_permission('volunteering'):
        return redirect(url_for('.schedule'))

    return redirect(url_for('.sign_up'))

from . import sign_up   # noqa: F401
from . import schedule  # noqa: F401
