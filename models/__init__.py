from main import db
from sqlalchemy import true


def exists(query):
    return db.session.query(true()).filter(query.exists()).scalar()


from .user import *  # noqa
from .payment import *  # noqa
from .cfp import *  # noqa
from .permission import *  # noqa
from .email import *  # noqa
from .ical import *  # noqa
from .product import * # noqa
from .purchase import * # noqa


db.configure_mappers()
