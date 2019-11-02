from ..flask_admin_base import VolunteerModelView

from main import volunteer_admin, db
from models.volunteer.volunteer import Volunteer


class VolunteerUserModelView(VolunteerModelView):
    column_searchable_list = ("nickname", "volunteer_email")
    column_filters = ["trained_roles", "allow_comms_during_event"]


volunteer_admin.add_view(
    VolunteerUserModelView(Volunteer, db.session, category="volunteers")
)
