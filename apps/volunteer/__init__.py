"""This app provides functionality for managing volunteers during the event.

Volunteer Registration
^^^^^^^^^^^^^^^^^^^^^^

Provided by `volunteer.sign_up` and `volunteer.choose_roles`, people who are
interested in volunteering can register themselves and select the roles they
want to do. Some roles

Shift Signup
^^^^^^^^^^^^

Provided by `volunteer.schedule`, shows the user what shifts are currently
available and allows them to either sign up for those shifts or cancel existing
shifts.

The schedule view also includes some advanced filtering which is available to
all users but is particularly intended for use by volunteer admins for quickly
locating shifts that need more people.

Training
^^^^^^^^

Some roles require a volunteer to be trained before they can sign up for any
shifts. In most cases this is performed by having them go to some sort of training
session, or just speaking to a team lead and being briefed, after which they're
marked as trained via the role admin pages.

In the case of bar roles we are legally required to show that our volunteer staff
have been properly inducted into licensing law which we do via the forms in
`volunteer.bar_training`.

Role Admin
^^^^^^^^^^

Users assigned admin privileges for a role can see a list of volunteers signed
up to current and upcoming shifts, allowing them to keep track of who should be
present, who needs relieving, and who's due to arrive soon. This view also allows
marking volunteers as having arrived or not.

Volunteer Admin
^^^^^^^^^^^^^^^

Available to people with the volunteer:admin permission, these views allow management
of role configuration such as descriptions and age requirements, shift timings,
and tracking down volunteer information.

Volunteer admins also have access to some configuration endpoints. These should
only be used if you know what you're doing, there is a strong potential for data
loss.

    * `/volunteer/init-shifts` loads shift configuration and creates the required
      database records.
    * `/volunteer/init-workshop-shifts` creates workshop manager shifts that
      coincide with scheduled workshops.
    * `/volunteer/clear-data` available only when debug mode is enabled, deletes
      all volunteer related data ready for reload.

Configuration Flags
^^^^^^^^^^^^^^^^^^^

The following flags are used to determine which parts of the public facing volunteer
system are visible to people, they get set manually once the neccessary prep has
been done.

    * `VOLUNTEERS_SIGNUP = True` enables volunteer registration functionality.
      This should only be enabled once all teams have confirmed which volunteer
      roles they want to fill.
    * `VOLUNTEERS_SCHEDULE = True` enables selection of specific shifts. This
      should only be enabled once all teams have confirmed their shift preferences.

If neither of these flags are set then going to /volunteer or clicking the Volunteer
menu item will redirect people to some static content about volunteering.
"""

from decorator import decorator
from flask import Blueprint, abort, redirect, request, url_for
from flask import current_app as app
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


from . import (
    api,  # noqa: F401
    bar_training,  # noqa: F401
    choose_roles,  # noqa: F401
    main,  # noqa: F401
    role_admin,  # noqa: F401
    schedule,  # noqa: F401
    sign_up,  # noqa: F401
    stats,  # noqa: F401
    team_admin,  # noqa: F401
    training,  # noqa: F401
)
