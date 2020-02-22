# coding=utf-8
from datetime import datetime

from main import db

class AdminMessage(db.Model):
    __tablename__ = "admin_message"
    __versioned__ = {}

    id = db.Column(db.Integer, primary_key=True)
    message = db.Column(db.String, nullable=False)
    show = db.Column(db.Boolean, nullable=False, default=False)

    end = db.Column(db.DateTime)

    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow
    )

    creator = db.relationship("User", backref="admin_messages")

    @property
    def is_visible(self):
        return self.show and (self.end is None or self.end > datetime.utcnow())

    @classmethod
    def get_visible_messages(cls):
        return [m for m in AdminMessage.query.all() if m.is_visible]

    @classmethod
    def get_all(cls):
        return AdminMessage.query.order_by(AdminMessage.created).all()

    @classmethod
    def get_by_id(cls, id):
        return AdminMessage.query.get_or_404(id)
