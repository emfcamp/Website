from main import db
from models.volunteer.role import Role, RoleAdmin

from ..flask_admin_base import VolunteerModelView
from . import volunteer_admin

volunteer_admin.add_view(VolunteerModelView(Role, db.session, name="Roles"))
volunteer_admin.add_view(VolunteerModelView(RoleAdmin, db.session, name="RoleAdmins"))
