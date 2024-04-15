from main import db
from datetime import datetime
from flask import current_app as app

from models import scheduled_task
from models.web_push import PushNotificationJob
from pywebpush import webpush, WebPushException


def deliver_notification(job: PushNotificationJob):
    """Deliver a push notification from a PushNotificationJob.

    The passed job will be mutated to reflect delivery state. A job which isn't
    queued will be skipped over.
    """
    if job.state != "queued":
        return

    try:
        webpush(
            subscription_info=job.target.subscription_info,
            data=job.title,
            vapid_private_key=app.config["WEBPUSH_PRIVATE_KEY"],
            vapid_claims={
                "sub": "mailto:contact@emfcamp.org",
            },
        )

        job.state = "delivered"
    except WebPushException as err:
        job.state = "failed"
        job.error = err.message


@scheduled_task(minutes=1)
def send_queued_notifications():
    jobs = PushNotificationJob.query.where(
        PushNotificationJob.state == "queued"
        and (
            PushNotificationJob.not_before is None
            or PushNotificationJob.not_before <= datetime.now()
        )
    ).all()

    for job in jobs:
        deliver_notification(job)
        db.session.add(job)

    db.session.commit()
