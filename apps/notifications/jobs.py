from sqlalchemy import and_
from main import db
from datetime import datetime, timedelta
from flask import current_app as app

from models import scheduled_task
from models.cfp import Proposal
from models.user import User
from models.web_push import PushNotificationJob
from models.notifications import UserNotificationPreference
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
        and (PushNotificationJob.not_before is None or PushNotificationJob.not_before <= datetime.now())
    ).all()

    for job in jobs:
        deliver_notification(job)
        db.session.add(job)

    db.session.commit()


@scheduled_task(minutes=15)
def queue_content_notifications(time=None) -> None:
    if time is None:
        time = datetime.now()

    users = User.query.join(
        UserNotificationPreference,
        User.notification_preferences.and_(UserNotificationPreference.favourited_content),
    )

    upcoming_content = Proposal.query.filter(
        and_(Proposal.scheduled_time >= time, Proposal.scheduled_time <= time + timedelta(minutes=16))
    ).all()

    for user in users:
        user_favourites = [f.id for f in user.favourites]
        favourites = [p for p in upcoming_content if p.id in user_favourites]
        for proposal in favourites:
            for target in user.web_push_targets:
                related_to = f"favourite,user:{user.id},proposal:{proposal.id},target:{target.id}"
                if (
                    PushNotificationJob.query.where(
                        PushNotificationJob.related_to == related_to
                    ).one_or_none()
                    is None
                ):
                    job = PushNotificationJob(
                        target=target,
                        title=f"{proposal.title} is happening soon at {proposal.scheduled_venue.name}",
                        related_to=related_to,
                        not_before=proposal.scheduled_time - timedelta(minutes=15),
                    )
                    print(f"Queued notification for {job.related_to}")
                    db.session.add(job)

    db.session.commit()
