from flask import Blueprint, request

from ..common import require_permission

volunteer = Blueprint('volunteer', __name__)

# User basically means they have signed up
# These aren't needed for the admin views as they have their auth baked in.
v_user_required = require_permission('volunteer:user')
v_admin_required = require_permission('volunteer:admin')
v_manager_required = require_permission('volunteer:manager')

@volunteer.context_processor
def volunteer_variables():
    return {
        'view_name': request.url_rule.endpoint.replace('volunteer.', '.')
    }


from . import main  # noqa: F401
from . import schedule  # noqa: F401
from . import sign_up  # noqa: F401
from . import choose_roles  # noqa: F401
