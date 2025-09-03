from datetime import datetime

from sqlalchemy import ForeignKey, func, select
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from models.user import User

from . import BaseModel, naive_utcnow

__all__ = ["EmailJob", "EmailJobRecipient"]


class EmailJob(BaseModel):
    __tablename__ = "email_job"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str]
    text_body: Mapped[str]
    html_body: Mapped[str]
    created: Mapped[datetime] = mapped_column(default=naive_utcnow)

    def __init__(self, subject, text_body, html_body):
        self.subject = subject
        self.text_body = text_body
        self.html_body = html_body

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
    # TODO: probably shouldn't be nullable
    sent: Mapped[bool | None] = mapped_column(default=False)

    user: Mapped[User] = relationship()
    job: Mapped[EmailJob] = relationship()

    def __init__(self, job, user):
        self.job = job
        self.user = user


EmailJob.recipient_count = column_property(
    select(func.count(EmailJobRecipient.job_id))
    .where(EmailJobRecipient.job_id == EmailJob.id)
    .scalar_subquery(),
    deferred=True,
)
