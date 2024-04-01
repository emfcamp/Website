from apps.common import json_response
from main import db
from flask import render_template, request, current_app as app
from flask_login import current_user, login_required

from . import notifications
from models.web_push import public_key, WebPushTarget


@notifications.route("/")
@login_required
def index():
    return render_template("notifications/index.html", public_key=public_key())


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
