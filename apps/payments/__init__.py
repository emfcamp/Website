from flask import Blueprint, render_template, current_app as app
from flask_mail import Message

from main import mail

from .common import get_user_payment_or_abort, lock_user_payment_or_abort  # noqa: F401

payments = Blueprint("payments", __name__)


def ticket_admin_email(title, template, **kwargs):
    if not app.config.get("TICKETS_NOTICE_EMAIL"):
        app.logger.warning("No tickets notice email configured, not sending")
        return

    msg = Message(
        "An EMF refund request has been received",
        sender=app.config.get("TICKETS_EMAIL"),
        recipients=[app.config.get("TICKETS_NOTICE_EMAIL")[1]],
    )
    msg.body = render_template(template, **kwargs)
    mail.send(msg)


from . import main  # noqa: F401
from . import banktransfer  # noqa: F401
from . import gocardless  # noqa: F401
from . import stripe  # noqa: F401
from . import invoice  # noqa: F401
from . import tasks  # noqa: F401
