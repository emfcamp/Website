from ..flask_admin_base import VolunteerModelView

from . import volunteer_admin
from main import db
from models.volunteer.role import Role

volunteer_admin.add_view(VolunteerModelView(Role, db.session, name="Roles"))
