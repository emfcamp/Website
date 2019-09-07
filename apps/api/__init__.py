from flask import Blueprint
from flask_restful import Api
from main import csrf

api_bp = Blueprint("api", __name__)
api = Api(api_bp, decorators=[csrf.exempt])

from . import user  # noqa
from . import map  # noqa
from . import schedule  # noqa
