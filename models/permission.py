from main import db

import models


class Permission(db.Model):
    __tablename__ = "permission"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, index=True)

    def __init__(self, name):
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


UserPermission = db.Table(
    "user_permission",
    db.Model.metadata,
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column(
        "permission_id", db.Integer, db.ForeignKey("permission.id"), primary_key=True
    ),
)
