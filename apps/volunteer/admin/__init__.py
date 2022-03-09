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


from . import role  # noqa: F401
from . import shift  # noqa: F401
from . import venue  # noqa: F401
from . import volunteer  # noqa: F401
