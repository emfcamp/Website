from decorator import decorator

from flask import Blueprint, request, current_app as app, redirect, url_for, abort
from flask_login import current_user

from models.volunteer import Volunteer

volunteer = Blueprint("volunteer", __name__)


# This is like require_permission but redirects to volunteer sign-up
def require_volunteer_permission(permission):
    def call(f, *args, **kwargs):
        if current_user.is_authenticated:
            if not Volunteer.get_for_user(current_user):
                return redirect(url_for("volunteer.sign_up", next=request.path))
            if current_user.has_permission(permission):
                return f(*args, **kwargs)
            abort(404)
        return app.login_manager.unauthorized()

    return decorator(call)


# User basically means they have signed up
# These aren't needed for the admin views as they have their auth baked in.
v_user_required = require_volunteer_permission("volunteer:user")
v_admin_required = require_volunteer_permission("volunteer:admin")
v_manager_required = require_volunteer_permission("volunteer:manager")


@volunteer.context_processor
def volunteer_variables():
    return {"view_name": request.url_rule.endpoint.replace("volunteer.", ".")}


from . import main  # noqa: F401
from . import schedule  # noqa: F401
from . import sign_up  # noqa: F401
from . import choose_roles  # noqa: F401
from . import training  # noqa: F401
from . import bar_training  # noqa: F401
from . import stats  # noqa: F401
from . import cards  # noqa: F401
