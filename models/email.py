from datetime import datetime
from main import db


class EmailJob(db.Model):
    __tablename__ = 'email_job'
    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String, nullable=False)
    text_body = db.Column(db.String, nullable=False)
    html_body = db.Column(db.String, nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __init__(self, subject, text_body, html_body):
        self.subject = subject
        self.text_body = text_body
        self.html_body = html_body


class EmailJobRecipient(db.Model):
    __tablename__ = 'email_recipient'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    job_id = db.Column(db.Integer, db.ForeignKey('email_job.id'), nullable=False)
    sent = db.Column(db.Boolean, default=False)

    def __init__(self, job, user):
        self.job = job
        self.user = user
