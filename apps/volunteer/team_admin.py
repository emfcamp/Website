from decorator import decorator
from flask import abort, flash, redirect, render_template, request, url_for
from flask import current_app as app
from flask.typing import ResponseReturnValue
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.orm import with_parent

from apps.volunteer import volunteer
from main import db, get_or_404
from models.volunteer.role import Team
from models.volunteer.volunteer import Volunteer


@decorator
def team_admin_required(f, *args, **kwargs):
    """Check that current user has permissions to be TeamAdmin for team.id that is first entry in args"""
    if current_user.is_authenticated:
        if int(args[0]) in current_user.volunteer.administered_team_ids or (
            current_user.has_permission("volunteer:admin")
        ):
            return f(*args, **kwargs)
        abort(404)
    return app.login_manager.unauthorized()


@volunteer.route("/team/<int:team_id>")
@team_admin_required
def team_admin(team_id: int) -> ResponseReturnValue:
    """Allow management of a team."""
    team = get_or_404(db, Team, team_id)
    return render_template("volunteer/team_admin.html", team=team)


@volunteer.route("/team/<int:team_id>/add_admin", methods=["POST"])
@team_admin_required
def add_team_admin(team_id: int) -> ResponseReturnValue:
    """Add an admin to a team."""
    team = get_or_404(db, Team, team_id)

    email_address = request.form["email"]
    volunteer = Volunteer.get_by_email(email_address)
    if volunteer is None:
        flash(f"No volunteer was found with the email address {email_address}.")
        return redirect(url_for(".team_admin", team_id=team_id))

    if volunteer not in team.admins:
        team.admins.append(volunteer)
        db.session.add(team)
        db.session.commit()

    flash(f"Added {volunteer.nickname} as a team admin.")
    return redirect(url_for(".team_admin", team_id=team_id))


@volunteer.route("/team/<int:team_id>/remove_admin/<int:volunteer_id>")
@team_admin_required
def remove_team_admin(team_id: int, volunteer_id: int) -> ResponseReturnValue:
    """Remove an admin from a team."""
    team = get_or_404(db, Team, team_id)
    volunteer = db.session.scalar(
        select(Volunteer).where(with_parent(team, Team.admins), Volunteer.id == volunteer_id)
    )

    if not volunteer:
        return redirect(url_for(".team_admin", team_id=team_id))

    team.admins.remove(volunteer)
    db.session.add(team)
    db.session.commit()

    flash(f"Removed {volunteer.nickname} as a team admin.")
    return redirect(url_for(".team_admin", team_id=team_id))
