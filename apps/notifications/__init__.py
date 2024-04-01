"""
    Notifications App

    Push/SMS notifcations and management thereof
"""

from flask import Blueprint

notifications = Blueprint("notifications", __name__)

from . import views  # noqa
