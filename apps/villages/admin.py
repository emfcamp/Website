"""Villages admin.

NOTE: make sure all admin views are tagged with the @village_admin_required decorator
"""

from flask import abort, flash, redirect, render_template, url_for
from flask import current_app as app
from flask.typing import ResponseReturnValue
from sqlalchemy import exists, select
from wtforms import StringField, SubmitField
from wtforms.validators import DataRequired
from wtforms.widgets import TextArea

from main import db
from models.user import User
from models.village import Village, VillageMember

from ..common import require_permission
from ..common.email import (
    enqueue_trusted_emails,
    format_trusted_html_email,
    preview_trusted_email,
)
from ..common.forms import Form
from . import villages
from .forms import (
    AddVillageAdminForm,
    AddVillageMemberForm,
    AdminVillageForm,
    DeleteVillageForm,
    DemoteVillageAdminForm,
    PromoteVillageMemberForm,
    RemoveVillageAdminForm,
    RemoveVillageMemberForm,
)

village_admin_required = require_permission("villages")


class EmailComposeForm(Form):
    subject = StringField("Subject", [DataRequired()])
    text = StringField("Text", [DataRequired()], widget=TextArea())
    preview = SubmitField("Preview Email")
    send_preview_address = StringField("Preview Email Address")
    send_preview = SubmitField("Send Preview Email")
    send = SubmitField("Send Email")


@villages.route("/admin")
@village_admin_required
def admin() -> ResponseReturnValue:
    villages = sorted(db.session.query(Village).all(), key=lambda v: v.name)

    return render_template("villages/admin/list.html", villages=villages)


@villages.route("/admin/village/<int:village_id>", methods=["GET", "POST"])
@village_admin_required
def admin_village(village_id: int) -> ResponseReturnValue:
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    form = AdminVillageForm()

    if form.validate_on_submit():
        assert form.name.data
        if db.session.execute(
            select(exists().where(Village.name == form.name.data, Village.id != village.id))
        ).scalar_one():
            flash("Another village with that name already exists!", "error")
        else:
            for venue in village.venues:
                if venue.name == village.name:
                    # Rename a village venue if it exists and has the old name.
                    venue.name = form.name.data

            form.populate_obj(village)
            db.session.add(village)
            db.session.commit()

            flash("The village has been updated")
        return redirect(url_for(".admin_village", village_id=village.id))

    form.populate(village)

    return render_template("villages/admin/info.html", village=village, form=form)


@villages.route("/admin/village/<int:village_id>/delete", methods=["GET", "POST"])
@village_admin_required
def delete(village_id: int) -> ResponseReturnValue:
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    form = DeleteVillageForm()
    if form.validate_on_submit():
        app.logger.info(f"Village '{village.name}' (id {village.id}) deleted")
        db.session.delete(village)
        db.session.commit()
        flash("Village deleted")
        return redirect(url_for(".admin"))

    return render_template("villages/admin/delete.html", village=village, form=form)


@villages.route("/admin/village/<int:village_id>/admins", methods=["GET"])
@village_admin_required
def admin_village_admins_get(village_id: int) -> ResponseReturnValue:
    return redirect(url_for(".admin_village", village_id=village_id))


### Village Admin actions
# Note that there are 2 uses of the word admin here.
# 1. the very small number of orga who can access the admin UI and change all villages
# 2. the attendees responsible for a single village who can administer just that village.
# These routes are for the former users to use to edit a list of the latter for a village


@villages.route("/admin/village/<int:village_id>/admins/remove", methods=["POST"])
@village_admin_required
def admin_village_admins_remove(village_id: int) -> ResponseReturnValue:
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    # Remove an admin
    if len(village.admins()) <= 1:
        flash("Can't remove final admin")
    else:
        form = RemoveVillageAdminForm()
        if form.validate_on_submit():
            village_membership = next(
                (
                    member
                    for member in village.village_memberships
                    if member.user_id == form.user_id.data
                    and member.admin
                ),
                None,
            )

            if village_membership is None:
                flash(f"User is not an admin of village '{village.name}'")
            else:
                # lazy-load this before committing and detaching the object
                email = village_membership.user.email

                db.session.delete(village_membership)
                db.session.commit()

                flash(f"{email} has been removed as a village admin")

    # Show the edit page again
    return redirect(url_for(".admin_village", village_id=village.id))


@villages.route("/admin/village/<int:village_id>/admins/demote", methods=["POST"])
@village_admin_required
def admin_village_admins_demote(village_id: int) -> ResponseReturnValue:
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    # Demote an admin to a normal non-admin member
    if len(village.admins()) <= 1:
        flash("Can't remove final admin")
    else:
        form = DemoteVillageAdminForm()
        if form.validate_on_submit():
            village_membership = next(
                (
                    member
                    for member in village.village_memberships
                    if member.user_id == form.user_id.data
                    and member.admin
                ),
                None,
            )

            if village_membership is None:
                flash(f"User is not an admin of village '{village.name}'")
            else:
                # lazy-load this before committing and detaching the object
                email = village_membership.user.email

                village_membership.admin = False
                db.session.commit()

                flash(f"{email} has been demoted from a village admin")

    # Show the edit page again
    return redirect(url_for(".admin_village", village_id=village.id))


@villages.route("/admin/village/<int:village_id>/admins/add", methods=["POST"])
@village_admin_required
def admin_village_admins_add(village_id: int) -> ResponseReturnValue:
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    # Add an admin
    form = AddVillageAdminForm()
    if form.validate_on_submit() and form.user_email.data is not None:
        user = User.get_by_email(form.user_email.data)

        if user is None:
            flash(f"No user found with email {form.user_email.data}")

        else:
            membership = db.session.query(VillageMember).filter(VillageMember.user == user).first()

            if membership is None:
                db.session.add(VillageMember(village_id=village.id, user=user, admin=True))
                db.session.commit()

                flash(f"{form.user_email.data} has been added as a village admin")
            else:
                if membership.village == village:
                    membership.admin = True
                    db.session.commit()

                    # TODO: Do we care if this actually changed anything?
                    flash(f"{form.user_email.data} has been promoted to a village admin")
                else:
                    flash(
                        f"User with email {form.user_email.data} is already a member of the {membership.village.name} village"
                    )

    # Show the edit page again
    return redirect(url_for(".admin_village", village_id=village.id))


### Village member actions


@villages.route("/admin/village/<int:village_id>/members/remove", methods=["POST"])
@village_admin_required
def admin_village_members_remove(village_id: int) -> ResponseReturnValue:
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    # Remove a non-admin
    form = RemoveVillageMemberForm()
    if form.validate_on_submit():
        village_membership = next(
            (
                member
                for member in village.village_memberships
                if member.user_id == form.user_id.data
                and not member.admin
            ),
            None,
        )

        if village_membership is None:
            flash(f"User is not a member of village '{village.name}'")
        else:
            # lazy-load this before committing and detaching the object
            email = village_membership.user.email

            db.session.delete(village_membership)
            db.session.commit()

            flash(f"{email} has been removed as a village member")

    # Show the edit page again
    return redirect(url_for(".admin_village", village_id=village.id))


@villages.route("/admin/village/<int:village_id>/members/promote", methods=["POST"])
@village_admin_required
def admin_village_members_promote(village_id: int) -> ResponseReturnValue:
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    form = PromoteVillageMemberForm()

    if form.validate_on_submit():
        village_membership = next(
            (
                member
                for member in village.village_memberships
                if member.user_id == form.user_id.data
                and not member.admin
            ),
            None,
        )

        if village_membership is None:
            flash(f"User is not a member of village '{village.name}'")
        else:
            # lazy-load this before committing and detaching the object
            email = village_membership.user.email

            village_membership.admin = True
            db.session.commit()

            flash(f"{email} has been promoted to a village admin")

    # Show the edit page again
    return redirect(url_for(".admin_village", village_id=village.id))


@villages.route("/admin/village/<int:village_id>/members/add", methods=["POST"])
@village_admin_required
def admin_village_members_add(village_id: int) -> ResponseReturnValue:
    village = Village.get_by_id(village_id)
    if not village:
        abort(404)

    # Add a non-admin
    form = AddVillageMemberForm()
    if form.validate_on_submit() and form.user_email.data is not None:
        user = User.get_by_email(form.user_email.data)

        if user is None:
            flash(f"No user found with email {form.user_email.data}")
        else:
            membership = db.session.query(VillageMember).filter(VillageMember.user == user).first()

            if membership is None:
                db.session.add(VillageMember(village_id=village.id, user=user, admin=False))
                db.session.commit()

                flash(f"{form.user_email.data} has been added as a village member")
            else:
                if membership.village == village:
                    membership.admin = False
                    db.session.commit()

                    # TODO: Do we care if this actually changed anything?
                    flash(f"{form.user_email.data} has been demoted to a village member")
                else:
                    flash(
                        f"User with email {form.user_email.data} is already a member of the {membership.village.name} village"
                    )

    # Show the edit page again
    return redirect(url_for(".admin_village", village_id=village.id))


## Email actions


@villages.route("/admin/email-owners", methods=["GET", "POST"])
@village_admin_required
def admin_email_owners() -> ResponseReturnValue:
    form = EmailComposeForm()
    if form.validate_on_submit():
        users = User.query.join(User.village_membership).filter(VillageMember.admin).distinct()
        if form.preview.data is True:
            return render_template(
                "villages/admin/email.html",
                html=format_trusted_html_email(form.text.data, form.subject.data),
                form=form,
                count=users.count(),
            )

        if form.send_preview.data is True:
            preview_trusted_email(form.send_preview_address.data, form.subject.data, form.text.data)

            flash(f"Email preview sent to {form.send_preview_address.data}")
            return render_template(
                "villages/admin/email.html",
                html=format_trusted_html_email(form.text.data, form.subject.data),
                form=form,
                count=users.count(),
            )

        if form.send.data is True:
            enqueue_trusted_emails(users, form.subject.data, form.text.data)
            flash(f"Email queued for sending to {users.count()} users")
            return redirect(url_for(".admin_email_owners"))

    return render_template("villages/admin/email.html", form=form)
