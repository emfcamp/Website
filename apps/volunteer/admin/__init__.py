from flask_admin import Admin

from apps.volunteer.flask_admin_base import VolunteerAdminIndexView

volunteer_admin = Admin(
    url="/volunteer/admin",
    name="EMF Volunteers",
    template_mode="bootstrap3",
    index_view=VolunteerAdminIndexView(url="/volunteer/admin"),
    base_template="volunteer/admin/flask-admin-base.html",
)
volunteer_admin.endpoint_prefix = "volunteer_admin"


from . import (
    buildup,  # noqa: F401
    role,  # noqa: F401
    shift,  # noqa: F401
    venue,  # noqa: F401
    volunteer,  # noqa: F401
)
