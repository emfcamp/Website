from datetime import datetime
from main import db

from sqlalchemy import func, select
from sqlalchemy.orm import column_property


class EmailJob(db.Model):
    __tablename__ = "email_job"
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String, nullable=False)
    text_body = db.Column(db.String, nullable=False)
    html_body = db.Column(db.String, nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

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


class EmailJobRecipient(db.Model):
    __tablename__ = "email_recipient"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey("email_job.id"), nullable=False)
    sent = db.Column(db.Boolean, default=False)

    user = db.relationship("User")
    job = db.relationship("EmailJob")

    def __init__(self, job, user):
        self.job = job
        self.user = user


EmailJob.recipient_count = column_property(
    select([func.count(EmailJobRecipient.job_id)]).where(
        EmailJobRecipient.job_id == EmailJob.id
    ),
    deferred=True,
)
