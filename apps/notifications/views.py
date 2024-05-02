from wtforms import SubmitField, BooleanField
from apps.common import json_response
from main import db
from flask import render_template, request, current_app as app, flash, redirect, url_for
from flask_login import current_user, login_required

from . import notifications
from ..common.forms import Form
from models.web_push import public_key, WebPushTarget, PushNotificationJob
from models.notifications import UserNotificationPreference


class PreferencesForm(Form):
    volunteer_shifts = BooleanField("Volunteer shifts")
    favourited_content = BooleanField("Favourited content")
    announcements = BooleanField("Announcements")
    save = SubmitField("Update preferences")


@notifications.route("/", methods=["GET", "POST"])
@login_required
def index():
    preferences = UserNotificationPreference.query.filter_by(user=current_user).first()
    if preferences is None:
        preferences = UserNotificationPreference(user=current_user)

    form = PreferencesForm(obj=preferences)
    if form.validate_on_submit():
        preferences.volunteer_shifts = form.volunteer_shifts.data
        preferences.favourited_content = form.favourited_content.data
        preferences.announcements = form.announcements.data
        db.session.add(preferences)
        db.session.commit()

    return render_template(
        "notifications/index.html", public_key=public_key(), form=form
    )


@notifications.route("/test", methods=["POST"])
@login_required
def test():
    if len(current_user.web_push_targets) == 0:
        flash("You have no devices configured for push notifications.")
        return redirect(url_for("notifications.index"))

    for target in current_user.web_push_targets:
        job = PushNotificationJob(
            target=target,
            title="This is a test notification.",
            related_to="test_notification",
        )
        db.session.add(job)
    db.session.commit()

    flash("Your notifications should arrive shortly.")
    return redirect(url_for("notifications.index"))


@notifications.route("/register", methods=["POST"])
@json_response
@login_required
def register():
    payload = request.json

    target = WebPushTarget.query.filter_by(
        user=current_user, endpoint=payload["endpoint"]
    ).first()

    if target is None:
        app.logger.info("Creating new target")
        target = WebPushTarget(
            user=current_user,
            endpoint=payload["endpoint"],
            subscription_info=payload,
            expires=payload.get("expires", None),
        )

        db.session.add(target)
        db.session.commit()
    else:
        app.logger.info("Using existing target")

    return {
        "id": target.id,
        "user_id": target.user_id,
    }
