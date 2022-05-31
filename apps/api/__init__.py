from flask import Blueprint
from flask_restful import Api

api_bp = Blueprint("api", __name__)
api = Api(api_bp)

from . import user  # noqa
from . import villages  # noqa
from . import schedule  # noqa
from . import installations  # noqa
