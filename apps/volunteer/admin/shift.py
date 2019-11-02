from ..flask_admin_base import VolunteerModelView

from main import volunteer_admin, db
from models.volunteer.shift import Shift


class ShiftModelView(VolunteerModelView):
    column_filters = ["role", "venue", "start", "end"]


volunteer_admin.add_view(ShiftModelView(Shift, db.session, category="shifts"))
