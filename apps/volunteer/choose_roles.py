from flask import (
    render_template,
    redirect,
    url_for,
    flash,
    request,
    abort,
    current_app as app,
)
from flask_login import current_user
from decorator import decorator

from wtforms import SubmitField, BooleanField, FormField, FieldList
from wtforms.validators import InputRequired

from datetime import datetime, timedelta

from main import db
from models.volunteer.role import Role
from models.volunteer.volunteer import Volunteer as VolunteerUser
from models.volunteer.shift import (
    Shift,
    ShiftEntry,
    ShiftEntryState,
    ShiftEntryStateException,
)

from . import volunteer, v_user_required
from ..common import feature_enabled, feature_flag
from ..common.forms import Form
from ..common.fields import HiddenIntegerField


class RoleSelectForm(Form):
    role_id = HiddenIntegerField("Role ID", [InputRequired()])
    signup = BooleanField("Role")


class RoleSignupForm(Form):
    roles = FieldList(FormField(RoleSelectForm))
    submit = SubmitField("Sign up for these roles")

    def add_roles(self, roles):
        # Don't add roles if some have already been set (this will get called
        # on POST as well as GET)
        if len(self.roles) == 0:
            for r in roles:
                self.roles.append_entry()
                self.roles[-1].role_id.data = r.id

        role_dict = {r.id: r for r in roles}
        # Enrich the field data
        for field in self.roles:
            field._role = role_dict[field.role_id.data]
            field.label = field._role.name

    def select_roles(self, role_ids):
        for r in self.roles:
            if r._role.id in role_ids:
                r.signup.data = True


# TODO need to actually implement permissions
@volunteer.route("/choose-roles", methods=["GET", "POST"])
@feature_flag("VOLUNTEERS_SIGNUP")
@v_user_required
def choose_role():
    form = RoleSignupForm()

    current_volunteer = VolunteerUser.get_for_user(current_user)
    if not current_volunteer.over_18:
        roles = Role.query.filter_by(over_18_only=False)
    else:
        roles = Role.query

    form.add_roles(roles.order_by(Role.name).all())

    if form.validate_on_submit():
        current_role_ids = [r.id for r in current_volunteer.interested_roles]

        for r in form.roles:
            r_id = r._role.id
            if r.signup.data and r_id not in current_role_ids:
                current_volunteer.interested_roles.append(r._role)

            elif not r.signup.data and r_id in current_role_ids:
                current_volunteer.interested_roles.remove(r._role)

        db.session.commit()
        if feature_enabled("VOLUNTEERS_SCHEDULE"):
            flash("Your role list has been updated", "info")
            return redirect(url_for(".schedule"))
        else:
            flash(
                "Thanks for volunteering! You'll be able to sign up for specific shifts soon.",
                "info",
            )
            return redirect(url_for(".choose_role"))

    current_roles = current_volunteer.interested_roles.all()
    if current_roles:
        role_ids = [r.id for r in current_roles]
        form.select_roles(role_ids)
    if uninterested_roles := [
        se.shift.role for se in current_user.shift_entries if se.shift.role not in current_roles
    ]:
        ui_roles_str = ", ".join([uir.name for uir in uninterested_roles])
        flash(
            f"You are still signed up for shifts for {ui_roles_str}. "
            + "Please cancel them from Shift sign-up if you don't want to do them."
        )
    return render_template("volunteer/choose_role.html", form=form)


@volunteer.route("/role_admin", methods=["GET"])
@v_user_required
def role_admin_index():
    roles = []
    if current_user.has_permission("admin") or current_user.has_permission("volunteer:manager"):
        roles = Role.query.order_by("name").all()
    else:
        roles = [admin.role for admin in current_user.volunteer_admin_roles]

    if len(roles) == 0:
        flash("You're not an admin for any roles.")
        redirect(url_for(".choose_role"))

    return render_template("volunteer/role_admin_index.html", roles=roles)


@volunteer.route("/role/<int:role_id>", methods=["GET", "POST"])
@feature_flag("VOLUNTEERS_SIGNUP")
@v_user_required
def role(role_id):
    role = Role.query.get_or_404(role_id)
    current_volunteer = VolunteerUser.get_for_user(current_user)
    current_role_ids = [r.id for r in current_volunteer.interested_roles]

    if request.method == "POST":
        if int(role_id) in current_role_ids:
            role_name = Role.query.get(role_id).name
            flash(
                f"You are already signed up to the {role_name} role. If you "
                "would like to remove it, please use the form below."
            )
        else:
            current_volunteer.interested_roles.append(role)
            db.session.commit()
            flash("Your role list has been updated", "info")

        return redirect(url_for(".choose_role"))

    return render_template(
        "volunteer/role.html",
        description=role.full_description,
        role=role,
        current_volunteer=current_volunteer,
    )


@decorator
def role_admin_required(f, *args, **kwargs):
    """Check that current user has permissions to be RoleAdmin for role.id that is first entry in args"""
    if current_user.is_authenticated:
        if int(args[0]) in [
            ra.role_id for ra in current_user.volunteer_admin_roles
        ] or current_user.has_permission("volunteer:admin"):
            return f(*args, **kwargs)
        abort(404)
    return app.login_manager.unauthorized()


@volunteer.route("role/<int:role_id>/admin")
@role_admin_required
def role_admin(role_id):
    # Allow mocking the time for testing.
    if "now" in request.args:
        now = datetime.strptime(request.args["now"], "%Y-%m-%dT%H:%M")
    else:
        now = datetime.now()

    limit = int(request.args.get("limit", "5"))
    offset = int(request.args.get("offset", "0"))
    role = Role.query.get_or_404(role_id)
    cutoff = now - timedelta(minutes=30)
    shifts = (
        Shift.query.filter_by(role=role)
        .filter(Shift.end >= cutoff)
        .order_by(Shift.end)
        .offset(offset)
        .limit(limit)
        .all()
    )

    active_shift_entries = (
        ShiftEntry.query.filter(ShiftEntry.state == "arrived")
        .join(ShiftEntry.shift)
        .filter(Shift.role_id == role.id)
        .all()
    )
    pending_shift_entries = (
        ShiftEntry.query.join(ShiftEntry.shift)
        .filter(
            Shift.start <= now - timedelta(minutes=15), Shift.role == role, ShiftEntry.state == "signed_up"
        )
        .all()
    )

    return render_template(
        "volunteer/role_admin.html",
        role=role,
        shifts=shifts,
        active_shift_entries=active_shift_entries,
        pending_shift_entries=pending_shift_entries,
        now=now,
        offset=offset,
        limit=limit,
    )


@volunteer.route("role/<int:role_id>/set_state/<int:shift_id>/<int:user_id>", methods=["POST"])
@role_admin_required
def set_state(role_id: int, shift_id: int, user_id: int):
    state = request.form["state"]

    try:
        se = ShiftEntry.query.filter(
            ShiftEntry.shift_id == shift_id, ShiftEntry.user_id == user_id
        ).first_or_404()
        if se.state != state:
            se.set_state(state)
        db.session.commit()
    except ShiftEntryStateException:
        flash(f"{state} is not a valid state for this shift.")

    return redirect(url_for(".role_admin", role_id=role_id))


@volunteer.route("role/<int:role_id>/volunteers")
@role_admin_required
def role_volunteers(role_id):
    role = Role.query.get_or_404(role_id)
    entries = ShiftEntry.query.filter(ShiftEntry.shift.has(role_id=role_id)).all()
    signed_up = list(set([se.user.volunteer for se in entries]))
    completed = list(set([se.user.volunteer for se in entries if se.completed]))
    return render_template(
        "volunteer/role_volunteers.html",
        role=role,
        signed_up=signed_up,
        completed=completed,
    )
