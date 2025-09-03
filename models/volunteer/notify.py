from datetime import datetime

from sqlalchemy import ForeignKey, func, select
from sqlalchemy.orm import Mapped, column_property, mapped_column, relationship

from .. import BaseModel, naive_utcnow


class VolunteerNotifyJob(BaseModel):
    __tablename__ = "volunteer_notify_job"
    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column()
    text_body: Mapped[str] = mapped_column()
    html_body: Mapped[str] = mapped_column()
    created: Mapped[datetime] = mapped_column(default=naive_utcnow)

    def __init__(self, subject, text_body, html_body):
        self.subject = subject
        self.text_body = text_body
        self.html_body = html_body


class VolunteerNotifyRecipient(BaseModel):
    __tablename__ = "volunteer_notify_recipient"
    id: Mapped[int] = mapped_column(primary_key=True)
    volunteer_id: Mapped[int] = mapped_column(ForeignKey("volunteer.id"))
    job_id: Mapped[int] = mapped_column(ForeignKey("volunteer_notify_job.id"))
    # TODO: shouldn't be nullable
    sent: Mapped[bool | None] = mapped_column(default=False)

    volunteer = relationship("Volunteer")
    job = relationship("VolunteerNotifyJob")

    def __init__(self, job, volunteer):
        self.job = job
        self.volunteer = volunteer


VolunteerNotifyJob.recipient_count = column_property(
    select(func.count(VolunteerNotifyRecipient.job_id))
    .where(VolunteerNotifyRecipient.job_id == VolunteerNotifyJob.id)
    .scalar_subquery(),
    deferred=True,
)
