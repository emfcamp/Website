from flask_login import current_user
from flask_restful import Resource, abort

# from models.user import User
from . import api


def user_info(user):
    return {
        # "url": api.url_for(UserInfo, user_id=user.id),
        "email": user.email,
        "name": user.name,
        "permissions": [p.name for p in user.permissions],
        "id": "/api/user/{}".format(user.id),
    }


class CurrentUserInfo(Resource):
    def get(self):
        if not current_user.is_authenticated:
            abort(401)
        return user_info(current_user)


# Need to think about permissions here and I don't need this anyway at the moment
# --Russ
# class UserInfo(Resource):
#    def get(self, user_id):
#        return user_info(User.get(user_id))


api.add_resource(CurrentUserInfo, "/user/current")
# api.add_resource(UserInfo, "/user/<int:user_id>")
