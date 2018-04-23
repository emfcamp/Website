
from main import volunteers, db

from .base import VolunteerModelView

from models.volunteers.venue import Venue

volunteers.add_view(VolunteerModelView(Venue, db.session, category="venues"))
