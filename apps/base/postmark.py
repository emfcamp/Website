"""Handler for Postmark webhooks, which notify us when emails bounce."""

from flask import abort, request
from flask import current_app as app
from flask.typing import ResponseReturnValue

from main import db
from models.user import User

from . import base


@base.route("/postmark-webhook", methods=["POST"])
def postmark_webhook() -> ResponseReturnValue:
    key = request.headers.get("X-Webhook-Key")
    if not key or key != app.config.get("POSTMARK_WEBHOOK_KEY"):
        abort(403)

    data = request.json

    user = User.get_by_email(data["Email"])

    if user is None:
        app.logger.warning(f"Postmark webhook for unknown email address {data['Email']}")
        return ""

    app.logger.info(f"Postmark {data['RecordType']} notification for {data['Email']} (user ID {user.id})")

    if data["RecordType"] == "Bounce":
        user.email_state = "bounced"
    elif data["RecordType"] == "SpamComplaint":
        user.email_state = "spam_report"

    db.session.commit()

    return ""
