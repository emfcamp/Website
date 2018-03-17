from flask import Blueprint

from ..common import require_permission

volunteers = Blueprint('volunteers', __name__)

# User basically means they have signed up
v_user_required = require_permission('volunteers:user')
v_admin_required = require_permission('volunteers:admin')
v_manager_required = require_permission('volunteers:manager')

from . import main  # noqa: F401
from . import venues  # noqa: F401
