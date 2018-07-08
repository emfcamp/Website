from flask import Blueprint

from ..common import require_permission

volunteer = Blueprint('volunteer', __name__)

# User basically means they have signed up
v_user_required = require_permission('volunteer:user')
v_admin_required = require_permission('volunteer:admin')
v_manager_required = require_permission('volunteer:manager')

from . import main  # noqa: F401
from . import venues  # noqa: F401
