from datetime import datetime

import pendulum
from sqlalchemy import ForeignKey, or_
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.functions import func

from . import BaseModel, naive_utcnow
from .user import User

__all__ = ["AdminMessage"]

INITIAL_TOPICS = {
    "heralds",
    "admin",
    "public",
}


class AdminMessage(BaseModel):
    __tablename__ = "admin_message"
    __versioned__: dict = {}

    id: Mapped[int] = mapped_column(primary_key=True)
    message: Mapped[str]
    show: Mapped[bool] = mapped_column(default=False)

    topic: Mapped[str | None]

    end: Mapped[datetime | None]

    created_by: Mapped[int] = mapped_column(ForeignKey("user.id"))

    created: Mapped[datetime] = mapped_column(default=naive_utcnow)
    modified: Mapped[datetime] = mapped_column(default=naive_utcnow, onupdate=naive_utcnow)

    creator: Mapped[User] = relationship(back_populates="admin_messages")

    def __init__(self, message, user, end=None, show=False, topic=None):
        self.message = message
        self.created_by = user.id

        if end:
            self.end = end
        else:
            self.end = pendulum.today().end_of("day")

        if show:
            self.show = show

        if topic:
            self.topic = topic

    @property
    def is_visible(self):
        return self.show and (self.end is None or self.end > naive_utcnow())

    @classmethod
    def get_visible_messages(cls):
        return [m for m in cls.get_all_for_topic("public") if m.is_visible]

    @classmethod
    def get_all(cls):
        return AdminMessage.query.order_by(AdminMessage.created).all()

    @classmethod
    def get_by_id(cls, id):
        return AdminMessage.query.get_or_404(id)

    @classmethod
    def get_all_for_topic(cls, topic):
        return AdminMessage.query.filter(
            AdminMessage.topic == topic,
            or_(
                AdminMessage.end > naive_utcnow(),
                AdminMessage.end == None,  # noqa: E711
            ),
        ).all()

    @classmethod
    def get_topic_counts(cls):
        res = {k: 0 for k in INITIAL_TOPICS}
        res.update(
            dict(
                AdminMessage.query.with_entities(
                    AdminMessage.topic,
                    func.count(AdminMessage.id).label("message_count"),
                )
                .group_by(AdminMessage.topic)
                .order_by(AdminMessage.topic)
                .all()
            )
        )
        return res
