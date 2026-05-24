from main import db
from models.volunteer.role import Role, RoleAdmin, Team

from ..flask_admin_base import VolunteerModelView
from . import volunteer_admin

volunteer_admin.add_view(VolunteerModelView(Team, db, name="Teams"))
volunteer_admin.add_view(VolunteerModelView(Role, db, name="Roles"))
volunteer_admin.add_view(VolunteerModelView(RoleAdmin, db, name="RoleAdmins"))
