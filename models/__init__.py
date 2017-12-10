from main import db
from sqlalchemy import true


def exists(query):
    return db.session.query(true()).filter(query.exists()).scalar()


from .user import *  # noqa: F401,F403
from .payment import *  # noqa: F401,F403
from .cfp import *  # noqa: F401,F403
from .permission import *  # noqa: F401,F403
from .email import *  # noqa: F401,F403
from .ical import *  # noqa: F401,F403
from .product import * # noqa: F401,F403
from .purchase import * # noqa: F401,F403


db.configure_mappers()
