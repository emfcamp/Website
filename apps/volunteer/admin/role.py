from ..flask_admin_base import VolunteerModelView

from main import volunteer_admin, db
from models.volunteer.role import Role

if volunteer_admin:
    volunteer_admin.add_view(VolunteerModelView(Role, db.session, name="Roles"))
