from ..flask_admin_base import VolunteerModelView

from . import volunteer_admin
from main import db
from models.volunteer.shift import Shift


class ShiftModelView(VolunteerModelView):
    column_filters = ["role", "venue", "start", "end"]


volunteer_admin.add_view(ShiftModelView(Shift, db.session, name="Shifts"))
