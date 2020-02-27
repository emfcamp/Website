from ..flask_admin_base import VolunteerModelView

from main import volunteer_admin, db
from models.volunteer.volunteer import Volunteer


class VolunteerUserModelView(VolunteerModelView):
    can_create = False
    can_delete = False
    can_set_page_size = True
    can_view_details = True
    column_details_exclude_list = ("user", "versions")
    column_details_list = (
        "nickname",
        "volunteer_email",
        "volunteer_phone",
        "planned_arrival",
        "planned_departure",
        "missing_shifts_opt_in",
        "over_18",
        "allow_comms_during_event",
        "banned",
    )
    column_filters = ["trained_roles", "allow_comms_during_event"]
    column_list = (
        "nickname",
        "volunteer_email",
        "planned_arrival",
        "planned_departure",
        "banned",
    )
    column_searchable_list = ("nickname", "volunteer_email")
    details_modal = True
    edit_modal = True
    form_columns = (
        "nickname",
        "volunteer_email",
        "volunteer_phone",
        "planned_arrival",
        "planned_departure",
        "interested_roles",
        "trained_roles",
        "missing_shifts_opt_in",
        "over_18",
        "allow_comms_during_event",
        "banned",
    )
    form_excluded_columns = ("user", "versions")
    page_size = 50  # the number of entries to display on the list view


# Add menu item Volunteers
volunteer_admin.add_view(
    VolunteerUserModelView(Volunteer, db.session, name="Volunteers")
)
