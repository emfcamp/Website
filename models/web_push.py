from datetime import datetime
from main import db
from flask import current_app as app
from pywebpush import webpush

from . import BaseModel


def public_key():
    return app.config["WEBPUSH_PUBLIC_KEY"]


def notify(target, message):
    webpush(
        subscription_info=target.subscription_info,
        data=message,
        vapid_private_key=app.config["WEBPUSH_PRIVATE_KEY"],
        vapid_claims={
            "sub": "mailto:contact@emfcamp.org",
        },
    )


class WebPushTarget(BaseModel):
    __table_name__ = "web_push_target"
    id = db.Column(db.Integer, primary_key=True)
    endpoint = db.Column(db.String, nullable=False)
    subscription_info = db.Column(db.JSON, nullable=False)
    expires = db.Column(db.DateTime, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    user = db.relationship("User")

    def __init__(self, user, endpoint, subscription_info, expires=None):
        self.user = user
        self.endpoint = endpoint
        self.subscription_info = subscription_info
        self.expires = expires
