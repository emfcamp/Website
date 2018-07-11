from ..flask_admin_base import VolunteerModelView

from main import volunteer_admin, db
from models.volunteer.shift import Shift

volunteer_admin.add_view(VolunteerModelView(Shift, db.session, category="shifts"))
