# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals

from flask import (
    render_template,
    redirect,
    request,
    flash,
    url_for,
    current_app as app,
    Blueprint,
    abort,
)

from flask_mail import Message
from flask_login import current_user

from main import mail
from models.volunteer import Volunteer, Role

from ..common import require_permission

from .forms import SendMessageForm

notify = Blueprint("notify", __name__)

admin_required = require_permission("admin")  # Decorator to require admin permissions
volunteer_admin_required = require_permission(
    "volunteer:admin"
)  # Decorator to require admin permissions


@notify.before_request
def admin_require_permission():
    """ Require admin permission for everything under /admin """
    if (
        not current_user.is_authenticated
        or not current_user.has_permission("admin")
        or not current_user.has_permission("volunteer:admin")
    ):
        abort(404)


@notify.route("")
def main():
    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".main")))

    if current_user.has_permission("volunteer:admin"):
        return redirect(url_for(".emailvolunteers"))

    if current_user.has_permission("admin"):
        return redirect(url_for(".emailvolunteers"))

    abort(404)


def get_volunteer_sort_dict(parameters):
    sort_keys = {"name": lambda v: (v.nickname, v.volunteer_email)}

    sort_by_key = parameters.get("sort_by")
    return {
        "key": sort_keys.get(sort_by_key, sort_keys["name"]),
        "reverse": bool(parameters.get("reverse")),
    }


def filter_volunteer_request():
    filtered = False

    desired_roles = request.args.getlist("role")
    if desired_roles:
        filtered = True
        volunteers = Volunteer.query.filter(
            Volunteer.interested_roles.any(Role.name.in_(desired_roles))
        ).all()
    else:
        volunteers = Volunteer.query.all()

    sort_dict = get_volunteer_sort_dict(request.args)

    volunteers.sort(**sort_dict)
    return volunteers, filtered


def get_ordered_roles():
    roles = Role.query.order_by(Role.name)
    role_names = []
    for role in roles:
        role_names.append(role.name)
    return role_names


@notify.route("/emailvolunteers")
@admin_required
def emailvolunteers():
    ordered_roles = get_ordered_roles()
    volunteers, filtered = filter_volunteer_request()
    non_sort_query_string = dict(request.args)

    if "sort_by" in non_sort_query_string:
        del non_sort_query_string["sort_by"]

    if "reverse" in non_sort_query_string:
        del non_sort_query_string["reverse"]

    return render_template(
        "notification/email_volunteers.html",
        volunteers=volunteers,
        new_qs=non_sort_query_string,
        roles=ordered_roles,
        filtered=filtered,
        total_volunteers=Volunteer.query.count(),
    )


@notify.route("/message_batch", methods=["GET", "POST"])
@volunteer_admin_required
def message_batch():
    volunteers, filtered = filter_volunteer_request()

    form = SendMessageForm()
    if form.validate_on_submit():
        if form.message.data and form.subject.data:
            for volunteer in volunteers:
                notify_email(volunteer, form.subject.data, form.message.data)

            flash("Emailed %s volunteers" % len(volunteers), "info")
            return redirect(url_for(".emailvolunteers", **request.args))
        else:
            flash("Subject and Message required.")

    return render_template(
        "notification/message_batch.html", form=form, volunteers=volunteers
    )


def notify_email(volunteer, subject, message):
    template = "notification/email/volunteer_request.txt"

    while True:
        msg = Message(
            subject,
            sender=app.config["VOLUNTEER_EMAIL"],
            recipients=[volunteer.volunteer_email],
        )
        msg.body = render_template(template, message=message, volunteer=volunteer)

        try:
            mail.send(msg)
            return True
        except AttributeError as e:
            app.logger.error(
                "Failed to email volunteer %s, ABORTING: %s",
                volunteer.volunteer_email,
                e,
            )
            return False
