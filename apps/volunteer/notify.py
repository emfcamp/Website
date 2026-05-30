from apps.common.email import (
    enqueue_emails,
    format_trusted_html_email,
    format_trusted_plaintext_email,
)
from main import db, mail

from ..config import config


def preview_trusted_notify(preview_address, subject, body):
    # This is basically a copy of apps.common.email.preview_trusted_email

    subject = "[PREVIEW] " + subject
    reason = f"You're receiving this notification because you have volunteered to help at Electromagnetic Field {config.event_year}."
    formatted_plaintext = format_trusted_plaintext_email(body)
    formatted_html = format_trusted_html_email(body, subject, reason)

    mail.send_mail(
        subject=subject,
        message=formatted_plaintext,
        html_message=formatted_html,
        from_email=config.from_email("VOLUNTEER_EMAIL"),
        recipient_list=[preview_address],
    )


def enqueue_trusted_notify(volunteers, subject, body):
    """Queue an notification for sending by the background worker."""
    # These are converted back to volunteers in the email sender because volunteer=True
    users = [v.user for v in volunteers]
    reason = f"You're receiving this notification because you have volunteered to help at Electromagnetic Field {config.event_year}."
    enqueue_emails(
        users=users,
        from_email=config.from_email("VOLUNTEER_EMAIL"),
        subject=subject,
        text_body=format_trusted_plaintext_email(body),
        html_body=format_trusted_html_email(body, subject, reason),
        priority=0,
        volunteer=True,
    )
    db.session.commit()
