import time

from flask import render_template, redirect, flash, url_for, current_app as app, request
from flask_login import current_user
from flask_mailman import EmailMessage
from wtforms import SubmitField, BooleanField, StringField
from wtforms.validators import DataRequired, ValidationError

from . import admin
from main import db
from sqlalchemy import func, or_
from sqlalchemy_continuum.utils import version_class

from models.user import User, generate_signup_code
from models.permission import Permission
from ..common.email import from_email
from ..common.forms import Form
from ..common.fields import EmailField


class NewUserForm(Form):
    name = StringField("Name", [DataRequired()])
    email = EmailField("Email")
    add = SubmitField("Add User")

    def validate_email(form, field):
        if User.does_user_exist(field.data):
            field.was_duplicate = True
            raise ValidationError("Account already exists")


@admin.route("/users", methods=["GET", "POST"])
def users():
    form = NewUserForm()

    if form.validate_on_submit():
        email, name = form.email.data, form.name.data
        user = User(email, name)

        db.session.add(user)
        db.session.commit()
        app.logger.info(
            "%s manually created new user with email %s and id: %s",
            current_user.id,
            email,
            user.id,
        )

        code = user.login_code(app.config["SECRET_KEY"])
        msg = EmailMessage(
            "Welcome to the EMF website",
            from_email=from_email("CONTACT_EMAIL"),
            to=[email],
        )
        msg.body = render_template(
            "emails/manually-added-user.txt", user=user, code=code
        )
        msg.send()

        flash("Created account for: %s" % name)
        return redirect(url_for(".users"))

    try:
        size = int(request.args.get("size", 500))
    except ValueError:
        return redirect(url_for(".users"))

    user_query = request.args.get("search", "")
    if user_query:
        select = db.select(User).where(
            or_(User.name.ilike(f"%{user_query}%"), User.email.ilike(f"%{user_query}%"))
        )
    else:
        select = db.select(User)

    users = select.order_by(User.id).options(
        db.joinedload(User.owned_admission_tickets), db.joinedload(User.permissions)
    )
    total_users = db.session.query(func.count(User.id)).scalar()
    users_paged = db.paginate(users, per_page=size, error_out=False)

    return render_template(
        "admin/users/users.html",
        users=users_paged,
        form=form,
        total_users=total_users,
        user_query=user_query,
    )


@admin.route("/users/<int:user_id>", methods=["GET", "POST"])
def user(user_id):
    user = User.query.filter_by(id=user_id).one()
    permissions = Permission.query.all()

    class UserForm(Form):
        note = StringField("Check-in note (will be shown to check-in operator)")
        add_note = SubmitField("Save Note")

        cfp_invite_reason = StringField("Indicates an invited speaker")
        save_cfp_invite_reason = SubmitField("Save invite reason")

        change_permissions = SubmitField("Change")
        new_name = StringField("New name")
        new_email = StringField("New email (will notify old and new emails if changed)")
        update_details = SubmitField("Update")

    for permission in permissions:
        setattr(
            UserForm,
            "permission_" + permission.name,
            BooleanField(
                permission.name, default=user.has_permission(permission.name, False)
            ),
        )

    form = UserForm()

    if form.validate_on_submit():
        if form.change_permissions.data:
            flash("Updated user's permissions")
            for permission in permissions:
                field = getattr(form, "permission_" + permission.name)
                if user.has_permission(permission.name, False) != field.data:
                    app.logger.info(
                        "user %s (%s) %s: %s -> %s",
                        user.name,
                        user.id,
                        permission.name,
                        user.has_permission(permission.name, False),
                        field.data,
                    )

                    if field.data:
                        user.grant_permission(permission.name)
                    else:
                        user.revoke_permission(permission.name)

        elif form.add_note.data:
            flash("Updated user's checkin note")
            user.checkin_note = form.note.data

        elif form.update_details.data:
            made_changes = []

            if form.new_name.data and form.new_name.data != user.name:
                app.logger.info(
                    "user %s name changed from %s to %s",
                    user.id,
                    user.name,
                    form.new_name.data,
                )
                user.name = form.new_name.data
                made_changes.append("name")

            if form.new_email.data and form.new_email.data != user.email:
                # NB: any login tokens that were previously generated and emailed will still be valid until expiry.
                # Maybe we should expire them and their sessions, just in case?
                old_email = user.email
                user.email = form.new_email.data
                app.logger.info(
                    "user %s (%s) email changed from %s to %s",
                    user.name,
                    user.id,
                    old_email,
                    form.new_email.data,
                )
                _send_email_changed_from(user, old_email)
                _send_email_changed_to(user, form.new_email.data)
                made_changes.append("email")

            if made_changes:
                flash(f'Updated user {" & ".join(made_changes)}')

        elif form.save_cfp_invite_reason.data:
            flash("Updated user's cfp invite reason")
            user.cfp_invite_reason = form.cfp_invite_reason.data

        db.session.commit()
        return redirect(url_for(".user", user_id=user.id))

    form.note.data = user.checkin_note
    form.new_name.data = user.name
    form.new_email.data = user.email

    versions = user.versions.order_by(None).order_by(
        version_class(User).transaction_id.desc()
    )

    form.note.data = user.checkin_note
    form.cfp_invite_reason.data = user.cfp_invite_reason
    return render_template(
        "admin/users/user.html", user=user, form=form, permissions=permissions
    )

    return render_template(
        "admin/users/user.html",
        user=user,
        form=form,
        permissions=permissions,
        versions=versions,
    )


def _send_email_changed_from(user: User, old_email: str) -> None:
    msg = EmailMessage(
        "Your email address has been changed",
        from_email=from_email("CONTACT_EMAIL"),
        to=[old_email],
    )
    msg.body = render_template("emails/user-email-changed-from.txt", user=user)
    msg.send()


def _send_email_changed_to(user: User, new_email: str) -> None:
    code = user.login_code(app.config["SECRET_KEY"])
    msg = EmailMessage(
        "Your email address has been changed",
        from_email=from_email("CONTACT_EMAIL"),
        to=[new_email],
    )
    msg.body = render_template("emails/user-email-changed.txt", user=user, code=code)
    msg.send()


class SignupForm(Form):
    create = SubmitField("Create link")


@admin.route("/user/signup", methods=["GET", "POST"])
def user_signup():
    form = SignupForm()

    code = None
    if form.validate_on_submit():
        app.logger.info("User %s creating signup link", current_user)
        code = generate_signup_code(
            app.config["SECRET_KEY"], time.time(), current_user.id
        )

    return render_template("admin/users/signup.html", form=form, code=code)
