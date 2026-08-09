from flask import flash, redirect, render_template, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user

from models.volunteer.volunteer import Volunteer

from . import v_admin_required, v_user_required, volunteer


def _recap_for(volunteer: Volunteer) -> ResponseReturnValue:
    return render_template(
        "volunteer/recap.html",
        volunteer=volunteer,
        shift_entries=volunteer.user.shift_entries,
    )


@volunteer.route("/recap")
@v_user_required
def recap() -> ResponseReturnValue:
    return _recap_for(Volunteer.get_for_user(current_user))


@volunteer.route("/recap/<email>")
@v_admin_required
def recap_by_email(email: str) -> ResponseReturnValue:
    volunteer = Volunteer.get_by_email(email)
    if volunteer is None:
        flash(f"No volunteer was found with email address {email}. Showing your recap instead.")
        return redirect(url_for(".recap"))

    return _recap_for(volunteer)
