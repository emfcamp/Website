import logging
from datetime import timedelta
from itertools import groupby
from typing import Any

from flask import current_app as app
from prometheus_client import Counter
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from main import db, mail
from models import naive_utcnow
from models.email import EmailJob, EmailJobRecipient
from models.scheduled_task import scheduled_task

logger = logging.getLogger(__name__)

EMAIL_YIELD_INTERVAL = timedelta(seconds=30)

email_yields = Counter("emf_email_yields", "Queued email yields")


@scheduled_task(minutes=1)
def send_emails() -> int:
    """
    Send queued emails in priority order, allowing for failure.

    The job only runs once a minute, so this isn't really suitable for time-sensitive emails.

    We yield if the process takes too long (e.g. mail server is struggling),
    as only one scheduled task can run at once.
    """

    start = naive_utcnow()

    recs: list[EmailJobRecipient] = list(
        db.session.scalars(
            select(EmailJobRecipient)
            .join(EmailJobRecipient.job)
            .options(
                joinedload(EmailJobRecipient.job),
            )
            .where(
                EmailJobRecipient.sent == False,
                EmailJobRecipient.sent_at.is_(None),
            )
            .order_by(
                EmailJob.priority,
                EmailJob.id,
                EmailJobRecipient.id,
            )
        )
    )

    count = 0
    for bulk, grouped_recs in groupby(recs, lambda r: r.job.bulk):
        if bulk:
            # Use config beginning BULK_MAIL_ on production-like systems (see apps/common/backends/bulk.py)
            backend = app.config.get("BULK_MAIL_BACKEND")
        else:
            backend = None

        with mail.get_connection(backend=backend) as conn:
            for rec in grouped_recs:
                count += send_email(conn, rec)

                if naive_utcnow() - start > EMAIL_YIELD_INTERVAL:
                    logger.warning("Email sending is taking too long, yielding")
                    email_yields.inc()
                    return count

    return count


def send_email(conn: Any, rec: EmailJobRecipient) -> int:
    if rec.job.volunteer:
        assert rec.user.volunteer
        recipient = rec.user.volunteer.volunteer_email
    else:
        recipient = rec.user

    sent_count: int = mail.send_mail(
        subject=rec.job.subject,
        message=rec.job.text_body,
        html_message=rec.job.html_body,
        from_email=rec.job.from_email,
        recipient_list=[recipient],
        fail_silently=True,
        connection=conn,
    )
    if sent_count > 0:
        rec.sent = True
        rec.sent_at = naive_utcnow()
        db.session.commit()

    return sent_count
