from ..flask_admin_base import VolunteerModelView

from . import volunteer_admin
from main import db
from models.volunteer.venue import VolunteerVenue

volunteer_admin.add_view(VolunteerModelView(VolunteerVenue, db.session, name="Venues"))
