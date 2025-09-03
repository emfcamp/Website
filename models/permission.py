from typing import TYPE_CHECKING

from sqlalchemy import Column, ForeignKey, Integer, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship

import models

from . import BaseModel

if TYPE_CHECKING:
    from .user import User

__all__ = [
    "Permission",
    "UserPermission",
]

UserPermission = Table(
    "user_permission",
    BaseModel.metadata,
    Column("user_id", Integer, ForeignKey("user.id"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("permission.id"), primary_key=True),
)


class Permission(BaseModel):
    __tablename__ = "permission"
    id: Mapped[int] = mapped_column(primary_key=True)
    # TODO: pretty sure this shouldn't be nullable
    name: Mapped[str | None] = mapped_column(unique=True, index=True)

    # TODO: should be `users`
    user: Mapped[list["User"]] = relationship(back_populates="permissions", secondary=UserPermission)

    def __init__(self, name: str):
        self.name = name

    @classmethod
    def get_export_data(cls):
        users = (
            cls.query.join(UserPermission)
            .join(models.User)
            .with_entities(models.User.id, models.User.email, Permission.name)
            .order_by(models.User.id, Permission.id)
        )

        data = {
            "private": {"permissions": users},
            "tables": ["permission", "user_permission"],
        }

        return data
