from main import db
from models import BaseModel
from datetime import datetime


class UserNotificationPreference(BaseModel):
    __table_name__ = "user_notification_preference"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    volunteer_shifts = db.Column(db.Boolean, default=False, nullable=False)
    favourited_content = db.Column(db.Boolean, default=False, nullable=False)
    announcements = db.Column(db.Boolean, default=False, nullable=False)

    user = db.relationship("User")

    def __init__(self, user):
        self.user = user
