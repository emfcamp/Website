from flask_login import current_user
from flask_restful import Resource, abort

from models.user import User

from . import api


def user_info(user):
    return {
        "url": api.url_for(UserInfo, user_id=user.id),
        "email": user.email,
        "name": user.name,
        "permissions": [p.name for p in user.permissions],
        "id": user.id,
    }


class CurrentUserInfo(Resource):
    def get(self):
        if not current_user.is_authenticated:
            abort(401)
        return user_info(current_user)


class UserInfo(Resource):
    def get(self, user_id):
        if not current_user.is_authenticated:
            abort(401)

        if (not current_user.has_permission("admin")) and current_user.id != user_id:
            abort(403)

        return user_info(User.query.get_or_404(user_id))


api.add_resource(CurrentUserInfo, "/user/current")
api.add_resource(UserInfo, "/user/<int:user_id>")
