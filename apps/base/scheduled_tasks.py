from main import mail, db
from models.email import EmailJobRecipient
from models.volunteer.notify import VolunteerNotifyRecipient
from models.scheduled_task import scheduled_task
from ..common.email import from_email


@scheduled_task(minutes=1)
def send_emails():
    """Send queued emails, allowing for failure"""
    count = 0
    with mail.get_connection() as conn:
        for rec in EmailJobRecipient.query.filter(
            EmailJobRecipient.sent == False  # noqa: E712
        ):
            count += send_email(conn, rec)
    return count


def send_email(conn, rec):
    sent_count = mail.send_mail(
        subject=rec.job.subject,
        message=rec.job.text_body,
        from_email=from_email("CONTACT_EMAIL"),
        recipient_list=[rec.user.email],
        fail_silently=True,
        connection=conn,
        html_message=rec.job.html_body,
    )
    if sent_count > 0:
        rec.sent = True
        db.session.add(rec)
        db.session.commit()
    return sent_count


@scheduled_task(minutes=1)
def send_volunteer_emails():
    """Send queued volunteer notifications"""
    count = 0
    with mail.get_connection() as conn:
        for rec in VolunteerNotifyRecipient.query.filter(
            VolunteerNotifyRecipient.sent == False  # noqa: E712
        ):
            count += send_volunteer_email(conn, rec)
    return count


def send_volunteer_email(conn, rec):
    sent_count = mail.send_mail(
        subject=rec.job.subject,
        message=rec.job.text_body,
        from_email=from_email("VOLUNTEER_EMAIL"),
        recipient_list=[rec.volunteer.volunteer_email],
        fail_silently=True,
        connection=conn,
        html_message=rec.job.html_body,
    )
    if sent_count > 0:
        rec.sent = True
        db.session.add(rec)
        db.session.commit()
    return sent_count
