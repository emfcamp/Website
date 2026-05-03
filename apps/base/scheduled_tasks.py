from flask import current_app as app
from sqlalchemy import func, select

from main import db, mail
from models.email import Email, EmailJobRecipient
from models.scheduled_task import scheduled_task
from models.volunteer.notify import VolunteerNotifyRecipient

from ..config import config


@scheduled_task(minutes=1)
def send_transactional_emails():
    """
    Send queued non-bulk emails, allowing for failure.

    As the job only runs once a minute, this isn't suitable for time-sensitive emails,
    but they'll usually be sent in-line anyway.
    """
    count = 0

    emails = list(db.session.scalars(select(Email).where(Email.sent_at.is_(None))))
    for email in emails:
        count += send_transactional_email(email)
    return count


def send_transactional_email(email: Email) -> int:
    sent_count: int = mail.send_mail(
        subject=email.subject,
        from_email=email.from_email,
        recipient_list=[email.recipient.email],
        message=email.text_body,
        html_message=email.html_body,
        fail_silently=True,
    )
    if sent_count > 0:
        email.sent_at = func.now()
        db.session.commit()
    return sent_count


@scheduled_task(minutes=1)
def send_bulk_emails():
    """Send queued bulk emails, allowing for failure"""
    count = 0

    # Sends via apps/common/backends/bulk.py
    with mail.get_connection(app.config.get("BULK_MAIL_BACKEND")) as conn:
        for rec in EmailJobRecipient.query.filter(EmailJobRecipient.sent == False):
            count += send_bulk_email(conn, rec)
    return count


def send_bulk_email(conn, rec):
    sent_count = mail.send_mail(
        subject=rec.job.subject,
        message=rec.job.text_body,
        html_message=rec.job.html_body,
        from_email=config.from_email("CONTACT_EMAIL"),
        recipient_list=[rec.user.email],
        fail_silently=True,
        connection=conn,
    )
    if sent_count > 0:
        rec.sent = True
        db.session.commit()
    return sent_count


@scheduled_task(minutes=1)
def send_volunteer_emails():
    """Send queued volunteer notifications"""
    count = 0
    with mail.get_connection() as conn:
        for rec in VolunteerNotifyRecipient.query.filter(VolunteerNotifyRecipient.sent == False):
            count += send_volunteer_email(conn, rec)
    return count


def send_volunteer_email(conn, rec):
    sent_count = mail.send_mail(
        subject=rec.job.subject,
        message=rec.job.text_body,
        from_email=config.from_email("VOLUNTEER_EMAIL"),
        recipient_list=[rec.volunteer.volunteer_email],
        fail_silently=True,
        connection=conn,
        html_message=rec.job.html_body,
    )
    if sent_count > 0:
        rec.sent = True
        db.session.commit()
    return sent_count
