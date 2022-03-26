from flask import current_app as app
from flask_mail import Message

from models.notify import VolunteerNotifyJob, VolunteerNotifyRecipient
from main import db, mail
from apps.common.email import format_trusted_html_email, format_trusted_plaintext_email


def preview_trusted_notify(preview_address, subject, body):
    subject = "[PREVIEW] " + subject
    formatted_html = format_trusted_html_email(
        body,
        subject,
        "You're receiving this notification because you have volunteered to help at Electromagnetic Field {event_year()}.",
    )

    with mail.connect() as conn:
        msg = Message(subject, sender=app.config["VOLUNTEER_EMAIL"])
        msg.add_recipient(preview_address)
        msg.body = format_trusted_plaintext_email(body)
        msg.html = formatted_html
        conn.send(msg)


def enqueue_trusted_notify(volunteers, subject, body, **kwargs):
    """Queue an notification for sending by the background worker."""
    job = VolunteerNotifyJob(
        subject,
        format_trusted_plaintext_email(body, **kwargs),
        format_trusted_html_email(body, subject, **kwargs),
    )
    db.session.add(job)

    for volunteer in volunteers:
        db.session.add(VolunteerNotifyRecipient(job, volunteer))

    db.session.commit()
