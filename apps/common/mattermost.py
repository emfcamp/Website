import requests
from flask import current_app as app


def mattermost_notify(channel: str, text: str) -> None:
    """Send a notification to a Mattermost channel"""
    webhook_url = app.config.get("MATTERMOST_WEBHOOK_URL")
    if not webhook_url:
        return

    message = {"channel": channel, "text": text}

    requests.post(webhook_url, json=message, timeout=3)
