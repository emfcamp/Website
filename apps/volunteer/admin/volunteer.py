from ..flask_admin_base import VolunteerModelView

from . import volunteer_admin
from flask import redirect, session, url_for
from flask import current_app as app
from flask_admin.actions import action
from main import db
from models.user import User
from models.volunteer import Volunteer
from wtforms.validators import ValidationError


class VolunteerUserModelView(VolunteerModelView):
    can_create = True
    can_delete = False
    can_set_page_size = True
    can_view_details = True
    column_details_exclude_list = ("user", "versions")
    column_details_list = (
        "nickname",
        "volunteer_email",
        "volunteer_phone",
        "over_18",
        "allow_comms_during_event",
        "banned",
    )
    column_filters = ["interested_roles", "allow_comms_during_event"]
    column_list = (
        "nickname",
        "volunteer_email",
        "banned",
    )
    column_searchable_list = ("nickname", "volunteer_email")
    details_modal = True
    edit_modal = True
    form_columns = (
        "nickname",
        "volunteer_email",
        "volunteer_phone",
        "interested_roles",
        "trained_roles",
        "admined_roles",
        "over_18",
        "allow_comms_during_event",
        "banned",
    )
    form_excluded_columns = ("user", "versions")
    page_size = 50  # the number of entries to display on the list view

    @action("notify", "Notify")
    def action_notify(self, ids):
        session["recipients"] = list(ids)
        return redirect(url_for("volunteer_admin_notify.main"))

    def on_model_change(self, form, model, is_created):
        # We don't care about updates, just create
        if is_created is False:
            return

        # Fetch form fields for convenience
        email = form.volunteer_email.data
        name = form.nickname.data

        # Turn off autoflush for the query so we don't insert first
        with db.session.no_autoflush:
            volunteer = Volunteer.query.filter_by(volunteer_email=email).first()
            user = User.get_by_email(email)

        # If the user doesn't exist go and create one
        if user is None:
            app.logger.info("No user record found for '%s', creating one", email)
            user = User(email, name)

        # If the volunteer exists already, error
        if volunteer:
            raise ValidationError("Volunteer already exists")

        # Set the user for the new volunteer record
        model.user = user
        user.grant_permission("volunteer:user")
        pass


# Add menu item Volunteers
volunteer_admin.add_view(
    VolunteerUserModelView(Volunteer, db.session, name="Volunteers")
)
