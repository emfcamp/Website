from datetime import datetime

from sqlalchemy import ForeignKey, func, select
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from models.user import User

from . import BaseModel, naive_utcnow

__all__ = ["Email", "EmailJob", "EmailJobRecipient"]


class EmailJob(BaseModel):
    __tablename__ = "email_job"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str]
    text_body: Mapped[str]
    html_body: Mapped[str]
    created: Mapped[datetime] = mapped_column(default=naive_utcnow)

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
    # TODO: replace with a timestamp like Email
    sent: Mapped[bool] = mapped_column(default=False)

    user: Mapped[User] = relationship()
    job: Mapped[EmailJob] = relationship()


EmailJob.recipient_count = column_property(
    select(func.count(EmailJobRecipient.job_id))
    .where(EmailJobRecipient.job_id == EmailJob.id)
    .scalar_subquery(),
    deferred=True,
)


class Email(BaseModel):
    """
    Transactional (i.e. non-bulk) email, for things like CfP updates.
    Having this in the DB allows us to link it to the rest of the database transaction.
    """

    __tablename__ = "email"
    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    from_email: Mapped[str]
    subject: Mapped[str]
    text_body: Mapped[str]
    html_body: Mapped[str | None]
    created: Mapped[datetime] = mapped_column(default=naive_utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(index=True)

    recipient: Mapped[User] = relationship()
