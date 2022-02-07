import markdown
from inlinestyler.utils import inline_css
from flask import render_template, Markup, url_for
from flask import current_app as app
from flask_mail import Message
from jinja2.sandbox import ImmutableSandboxedEnvironment

from models import event_year
from models.email import EmailJob, EmailJobRecipient
from main import db, mail


def create_sandbox_env():
    default_jinja_options = {}
    if app.jinja_options != default_jinja_options:
        # This code doesn't support any unusual options (yet)
        raise NotImplementedError

    # Don't autoescape because this is used to generate plaintext output
    env = ImmutableSandboxedEnvironment(autoescape=False)

    config_to_copy = [
        "DEBUG",
        "SERVER_NAME",
    ]
    config = {c: app.config[c] for c in config_to_copy if c in app.config}

    # We don't need things like request and session for emails
    env.globals.update(
        url_for=url_for,
        config=config,
    )
    return env


def build_template_context():
    ctx = {}
    for func in app.template_context_processors[None]:
        ctx.update(func())

    # We don't need things like request and session for emails
    context_to_copy = [
        "external_url",
        "simple_dates",
        "event_start",
        "event_end",
        "event_year",
    ]
    ctx = {k: ctx[k] for k in context_to_copy}
    return ctx


def render_template_string_sandboxed(template_str, **kwargs):
    env = create_sandbox_env()
    template = env.from_string(template_str)
    return template.render(**build_template_context(), **kwargs)


def format_trusted_html_email(markdown_text, subject, reason=None, **kwargs):
    """Render a Markdown-formatted string to an HTML email.

    markdown_text is rendered as a template. We render in the Jinja
    sandbox, with a cut-down environment. This could still expose
    interesting things unintentionally, so don't run templates from
    untrusted users.

    **kwargs are used to substitute variables in the Markdown string,
    and are considered trusted. Do not pass user-controlled data in,
    unless you're happy for that user to insert arbitrary HTML into
    the email.
    """

    extensions = ["markdown.extensions.nl2br", "markdown.extensions.smarty"]
    markdown_text = render_template_string_sandboxed(markdown_text, **kwargs)
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


def format_trusted_plaintext_email(markdown_text, **kwargs):
    """Render a Markdown-formatted string to a plaintext email.

    markdown_text is rendered as a template, so is considered trusted.
    Do not pass user-controlled templates in, unless you're happy for
    that user to run code on the server.
    """
    return render_template_string_sandboxed(markdown_text, **kwargs)


def preview_trusted_email(preview_address, subject, body):
    subject = "[PREVIEW] " + subject
    formatted_html = format_trusted_html_email(body, subject)

    with mail.connect() as conn:
        msg = Message(subject, sender=app.config["CONTACT_EMAIL"])
        msg.add_recipient(preview_address)
        msg.body = format_trusted_plaintext_email(body)
        msg.html = formatted_html
        conn.send(msg)


def enqueue_trusted_emails(users, subject, body, **kwargs):
    """Queue an email for sending by the background email worker."""
    job = EmailJob(
        subject,
        format_trusted_plaintext_email(body, **kwargs),
        format_trusted_html_email(body, subject, **kwargs),
    )
    db.session.add(job)

    for user in users:
        db.session.add(EmailJobRecipient(job, user))

    db.session.commit()
