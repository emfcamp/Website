from models import event_year
from models.volunteer.notify import VolunteerNotifyJob, VolunteerNotifyRecipient
from main import db, mail
from apps.common.email import format_trusted_html_email, format_trusted_plaintext_email


def preview_trusted_notify(preview_address, subject, body):
    subject = "[PREVIEW] " + subject
    reason = f"You're receiving this notification because you have volunteered to help at Electromagnetic Field {event_year()}."
    formatted_plaintext = format_trusted_plaintext_email(body)
    formatted_html = format_trusted_html_email(body, subject, reason)

    mail.send_mail(
        subject=subject,
        message=formatted_plaintext,
        from_email=app.config["VOLUNTEER_EMAIL"],
        recipient_list=[preview_address],
        html_message=formatted_html,
    )


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
