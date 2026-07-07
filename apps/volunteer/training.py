from collections.abc import Sequence

from flask import flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user

from apps.volunteer.role_admin import role_admin_required
from main import db
from models.volunteer.role import Role
from models.volunteer.volunteer import Volunteer

from . import v_user_required, volunteer


@volunteer.route("/training")
@v_user_required
def training_index() -> ResponseReturnValue:
    volunteer: Volunteer = current_user.volunteer

    if volunteer.is_volunteer_admin:
        all_roles = volunteer.administered_roles
    else:
        all_roles = volunteer.interested_roles

    roles = [
        role
        for role in all_roles
        if (role.training_notes is not None and role.training_notes != "")
        or (role.requires_training and not role.uses_bar_training)
    ]

    if volunteer.over_18:
        bar_roles = [role for role in all_roles if role.uses_bar_training]
        if bar_roles:
            roles.append(bar_roles[0])

    return render_template(
        "volunteer/training.html",
        roles=sorted(roles, key=lambda r: r.name),
        trained_roles=volunteer.trained_roles.all(),  # type: ignore
    )


@volunteer.route("/training/<int:role_id>", methods=["GET", "POST"])
@v_user_required
def training(role_id: int) -> ResponseReturnValue:
    role = Role.get_by_id(role_id)
    if not role.requires_training and (role.training_notes is None or role.training_notes.strip() == ""):
        flash(f"{role.name} doesn't require any training.")
        return redirect(url_for(".choose_role"))

    if request.method == "GET":
        return render_template("volunteer/role_training.html", role=role)

    if not role.allows_self_training:
        flash("Nice try. This role doesn't allow self training.")
        return redirect(url_for(".training", role_id=role.id))

    role.trained_volunteers.append(current_user.volunteer)
    db.session.commit()

    flash(f"Thanks! You're now trained for {role.name} and can sign up for shifts.")
    return redirect("/volunteer")


@volunteer.route("/role-admin/<role_id>/train-users", methods=["GET", "POST"])
@role_admin_required
def train_users(role_id: int) -> ResponseReturnValue:
    role = Role.get_by_id(role_id)

    volunteers: Sequence[Volunteer] = []
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
