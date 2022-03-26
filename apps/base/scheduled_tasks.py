from flask_mail import Message
from flask import current_app as app
from main import mail, db

from models.email import EmailJobRecipient
from models.volunteer.notify import VolunteerNotifyRecipient
from models.scheduled_task import scheduled_task


@scheduled_task(minutes=1)
def send_emails():
    """Send queued emails"""
    count = 0
    with mail.connect() as conn:
        for rec in EmailJobRecipient.query.filter(
            EmailJobRecipient.sent == False  # noqa: E712
        ):
            count += 1
            send_email(conn, rec)
    return count


def send_email(conn, rec):
    msg = Message(rec.job.subject, sender=app.config["CONTACT_EMAIL"])
    msg.add_recipient(rec.user.email)
    msg.body = rec.job.text_body
    msg.html = rec.job.html_body
    conn.send(msg)
    rec.sent = True
    db.session.add(rec)
    db.session.commit()


def send_volunteer_emails():
    """Send queued volunteer notifications"""
    count = 0
    with mail.connect() as conn:
        for rec in VolunteerNotifyRecipient.query.filter(
            VolunteerNotifyRecipient.sent == False  # noqa: E712
        ):
            count += 1
            send_volunteer_email(conn, rec)
    return count


def send_volunteer_email(conn, rec):
    msg = Message(rec.job.subject, sender=app.config["VOLUNTEER_EMAIL"])
    msg.add_recipient(rec.volunteer.email)
    msg.body = rec.job.text_body
    msg.html = rec.job.html_body
    conn.send(msg)
    rec.sent = True
    db.session.add(rec)
    db.session.commit()
