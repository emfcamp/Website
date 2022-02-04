from main import db
from . import BaseModel
import sqlalchemy

import models


class Permission(BaseModel):
    __tablename__ = "permission"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, index=True)

    def __init__(self, name: str):
        self.name = name

    @classmethod
    def get_export_data(cls):
        users = (
            cls.query.join(UserPermission, models.User)
            .with_entities(models.User.id, models.User.email, Permission.name)
            .order_by(models.User.id, Permission.id)
        )

        data = {
            "private": {"permissions": users},
            "tables": ["permission", "user_permission"],
        }

        return data


UserPermission: sqlalchemy.Table = db.Table(
    "user_permission",
    BaseModel.metadata,
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column(
        "permission_id", db.Integer, db.ForeignKey("permission.id"), primary_key=True
    ),
)
