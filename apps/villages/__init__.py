"""
    Villages App

    Village registration and management
"""
from flask import Blueprint, abort
from flask_login import current_user
from models import event_year
from models.village import Village

villages = Blueprint("villages", __name__)


def load_village(year, village_id, require_admin=False):
    """Helper to return village or 404"""
    if year != event_year():
        abort(404)

    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    if require_admin and not (
        current_user.village.village == village and current_user.village.admin
    ):
        abort(404)
    return village


from . import views  # noqa
from . import admin  # noqa
