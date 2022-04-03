from datetime import datetime
from main import db

from sqlalchemy import func, select
from sqlalchemy.orm import column_property

from . import BaseModel


class VolunteerNotifyJob(BaseModel):
    __tablename__ = "volunteer_notify_job"
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String, nullable=False)
    text_body = db.Column(db.String, nullable=False)
    html_body = db.Column(db.String, nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __init__(self, subject, text_body, html_body):
        self.subject = subject
        self.text_body = text_body
        self.html_body = html_body


class VolunteerNotifyRecipient(BaseModel):
    __tablename__ = "volunteer_notify_recipient"
    id = db.Column(db.Integer, primary_key=True)
    volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteer.id"), nullable=False)
    job_id = db.Column(
        db.Integer, db.ForeignKey("volunteer_notify_job.id"), nullable=False
    )
    sent = db.Column(db.Boolean, default=False)

    volunteer = db.relationship("Volunteer")
    job = db.relationship("VolunteerNotifyJob")

    def __init__(self, job, volunteer):
        self.job = job
        self.volunteer = volunteer


VolunteerNotifyJob.recipient_count = column_property(
    select([func.count(VolunteerNotifyRecipient.job_id)]).where(
        VolunteerNotifyRecipient.job_id == VolunteerNotifyJob.id
    ),
    deferred=True,
)
