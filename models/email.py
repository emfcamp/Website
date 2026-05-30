from datetime import datetime

from sqlalchemy import ForeignKey, func, select
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from main import NaiveDT
from models.user import User

from . import BaseModel, naive_utcnow

__all__ = ["EmailJob", "EmailJobRecipient"]


class EmailJob(BaseModel):
    """A fixed-content email, which may be sent to multiple recipients"""

    __tablename__ = "email_job"
    id: Mapped[int] = mapped_column(primary_key=True)
    #: Order in which to send emails, 0 is highest priority
    priority: Mapped[int]
    #: Send via the bulk SMTP server
    bulk: Mapped[bool]
    #: Send to the user's volunteering contact address
    volunteer: Mapped[bool]
    from_email: Mapped[str]
    subject: Mapped[str]
    text_body: Mapped[str]
    html_body: Mapped[str | None]
    created: Mapped[datetime] = mapped_column(default=naive_utcnow)

    recipients: Mapped[list[EmailJobRecipient]] = relationship(back_populates="job")

    @classmethod
    def get_export_data(cls):
        jobs = cls.query.with_entities(
            cls.subject, cls.created, cls.recipient_count, cls.text_body, cls.html_body
        )
        data = {"public": {"jobs": jobs}, "tables": ["email_job", "email_recipient"]}

        return data


class EmailJobRecipient(BaseModel):
    __tablename__ = "email_recipient"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    job_id: Mapped[int] = mapped_column(ForeignKey("email_job.id"))
    # TODO after 2026: remove/replace with column_property
    sent: Mapped[bool] = mapped_column(default=False)
    sent_at: Mapped[NaiveDT | None] = mapped_column(index=True)

    user: Mapped[User] = relationship(back_populates="email_job_recipients")
    job: Mapped[EmailJob] = relationship(back_populates="recipients")


EmailJob.recipient_count = column_property(
    select(func.count(EmailJobRecipient.job_id))
    .where(EmailJobRecipient.job_id == EmailJob.id)
    .scalar_subquery(),
    deferred=True,
)
