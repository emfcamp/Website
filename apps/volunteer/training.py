from flask import current_app as app
from flask import flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue

from apps.volunteer.role_admin import role_admin_required
from main import db
from models.volunteer.role import Role
from models.volunteer.volunteer import Volunteer

from . import volunteer


@volunteer.route("/role-admin/<role_id>/train-users", methods=["GET", "POST"])
@role_admin_required
def train_users(role_id: int) -> ResponseReturnValue:
    role = Role.get_by_id(role_id)

    volunteers = []
    if request.method == "POST" and request.form["query"] != "":
        volunteers = Volunteer.find_by_query(request.form["query"])

    # if form.validate_on_submit():
    #     changes = 0
    #     for v in form.volunteers:
    #         if v.trained.data and v._volunteer not in role.trained_volunteers:
    #             changes += 1
    #             role.trained_volunteers.append(v._volunteer)

    #         elif not v.trained.data and v._volunteer in role.trained_volunteers:
    #             changes += 1
    #             role.trained_volunteers.remove(v._volunteer)

    #     db.session.commit()
    #     flash(f"Trained {changes} volunteers")
    #     app.logger.info(f"Trained {changes} volunteers")

    #     return redirect(url_for(".train_users", role_id=role_id))

    return render_template(
        "volunteer/training/train_users.html",
        role=role,
        query=request.form.get("query", ""),
        volunteers=volunteers,
    )


@volunteer.route("/role-admin/<int:role_id>/train-users/<int:volunteer_id>", methods=["POST"])
@role_admin_required
def train_user(role_id: int, volunteer_id: int) -> ResponseReturnValue:
    role = Role.get_by_id(role_id)
    volunteer = Volunteer.get_by_id(volunteer_id)

    role.trained_volunteers.append(volunteer)
    db.session.commit()

    flash(f"Marked {volunteer.nickname} trained")
    return redirect(url_for(".train_users", role_id=role_id))


@volunteer.route("/role-admin/<int:role_id>/train-users/<int:volunteer_id>/untrain", methods=["POST"])
@role_admin_required
def untrain_user(role_id: int, volunteer_id: int) -> ResponseReturnValue:
    role = Role.get_by_id(role_id)
    volunteer = Volunteer.get_by_id(volunteer_id)

    role.trained_volunteers.remove(volunteer)
    db.session.commit()

    flash(f"Marked {volunteer.nickname} untrained")
    return redirect(url_for(".train_users", role_id=role_id))
