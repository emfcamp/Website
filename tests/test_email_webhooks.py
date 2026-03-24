import json
from pathlib import Path

from flask import url_for


def load_webhook(name):
    fixture_path = Path(__file__).parent / "webhook_fixtures" / "postmark"

    with open(fixture_path / f"{name}.json") as f:
        return json.load(f)


def test_email_bounce_handling(user, client, app, request_context):
    assert user.email_state == "unverified"

    key = app.config["POSTMARK_WEBHOOK_KEY"] = "abc123"

    bounce_webhook = load_webhook("bounce")
    bounce_webhook["Email"] = user.email

    res = client.post(url_for("base.postmark_webhook"), json=bounce_webhook, headers={"X-Webhook-Key": key})
    assert res.status_code == 200

    assert user.email_state == "bounced"

    spam_complaint_webhook = load_webhook("spam_complaint")
    spam_complaint_webhook["Email"] = user.email
    res = client.post(
        url_for("base.postmark_webhook"), json=spam_complaint_webhook, headers={"X-Webhook-Key": key}
    )
    assert res.status_code == 200

    assert user.email_state == "spam_report"
