from datetime import datetime
from typing import Literal
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
    jobs = db.relationship(
        "PushNotificationJob",
        backref="target",
        cascade="all, delete-orphan",
    )

    def __init__(self, user, endpoint, subscription_info, expires=None):
        self.user = user
        self.endpoint = endpoint
        self.subscription_info = subscription_info
        self.expires = expires


class PushNotificationJob(BaseModel):
    __table_name__ = "web_push_notification_job"
    id: int = db.Column(db.Integer, primary_key=True)
    target_id: int = db.Column(
        db.Integer, db.ForeignKey("web_push_target.id"), nullable=False
    )
    created: datetime = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    state: Literal["queued", "delivered", "failed"] = db.Column(
        db.String, default="queued", nullable=False
    )
    not_before: datetime | None = db.Column(db.DateTime, nullable=True)
    related_to: str | None = db.Column(db.String, nullable=True)
    title: str = db.Column(db.String, nullable=False)
    body: str | None = db.Column(db.String, nullable=True)
    error: str | None = db.Column(db.String, nullable=True)

    def __init__(
        self,
        target: WebPushTarget,
        title: str,
        body: str | None = None,
        related_to: str | None = None,
        not_before: datetime | None = None,
    ) -> None:
        self.target = target
        self.title = title
        self.body = body
        self.related_to = related_to
        self.not_before = not_before
