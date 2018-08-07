from flask import abort
from flask_login import current_user
from flask_restful import Resource
from models.user import User
from . import api


def user_info(user):
    return {
        "url": api.url_for(UserInfo, user_id=user.id),
        "email": user.email,
        "name": user.name,
        "permissions": [p.name for p in user.permissions],
    }


class CurrentUserInfo(Resource):
    def get(self):
        if not current_user:
            abort(404)
        return user_info(current_user)


class UserInfo(Resource):
    def get(self, user_id):
        return user_info(User.get(user_id))


api.add_resource(CurrentUserInfo, "/user/current")
api.add_resource(UserInfo, "/user/<int:user_id>")
