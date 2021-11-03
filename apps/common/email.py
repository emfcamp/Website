import markdown
from inlinestyler.utils import inline_css
from flask import render_template, Markup
from flask import current_app as app
from flask_mail import Message

from models.email import EmailJob, EmailJobRecipient
from main import db, mail


def format_html_email(markdown_text, subject):
    extensions = ["markdown.extensions.nl2br", "markdown.extensions.smarty"]
    markdown_html = Markup(markdown.markdown(markdown_text, extensions=extensions))
    return inline_css(
        render_template(
            "admin/email/email_template.html", subject=subject, content=markdown_html
        )
    )


def format_plaintext_email(markdown_text):
    return markdown_text


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


def enqueue_emails(users, subject, body):
    job = EmailJob(
        subject,
        format_plaintext_email(body),
        format_html_email(body, subject),
    )
    db.session.add(job)

    for user in users:
        db.session.add(EmailJobRecipient(job, user))
    db.session.commit()
