import markdown
from inlinestyler.utils import inline_css
from flask import render_template, render_template_string, Markup
from flask import current_app as app
from flask_mail import Message

from models import event_year
from models.email import EmailJob, EmailJobRecipient
from main import db, mail


def format_html_email(markdown_text, subject, reason=None, **kwargs):
    """Render a Markdown-formatted string to an HTML email.

    **kwargs are used to substitute variables in the Markdown string.
    """
    extensions = ["markdown.extensions.nl2br", "markdown.extensions.smarty"]
    markdown_text = render_template_string(markdown_text, **kwargs)
    markdown_html = Markup(markdown.markdown(markdown_text, extensions=extensions))

    if not reason:
        reason = f"You're receiving this email because you have a ticket for Electromagnetic Field {event_year()}."

    return inline_css(
        render_template(
            "admin/email/email_template.html",
            subject=subject,
            content=markdown_html,
            reason=reason,
        )
    )


def format_plaintext_email(markdown_text, **kwargs):
    return render_template_string(markdown_text, **kwargs)


def preview_email(preview_address, subject, body):
    subject = "[PREVIEW] " + subject
    formatted_html = format_html_email(body, subject)
    preview_email = preview_address

    with mail.connect() as conn:
        msg = Message(subject, sender=app.config["CONTACT_EMAIL"])
        msg.add_recipient(preview_email)
        msg.body = format_plaintext_email(body)
        msg.html = formatted_html
        conn.send(msg)


def enqueue_emails(users, subject, body, **kwargs):
    """Queue an email for sending by the background email worker."""
    job = EmailJob(
        subject,
        format_plaintext_email(body, **kwargs),
        format_html_email(body, subject, **kwargs),
    )
    db.session.add(job)

    for user in users:
        db.session.add(EmailJobRecipient(job, user))

    db.session.commit()
