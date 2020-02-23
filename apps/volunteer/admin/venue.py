from ..flask_admin_base import VolunteerModelView

from main import volunteer_admin, db
from models.volunteer.venue import VolunteerVenue

volunteer_admin.add_view(
    VolunteerModelView(VolunteerVenue, db.session, category="Settings", name="Venues")
)
