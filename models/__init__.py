from main import db
from sqlalchemy import true

def exists(query):
    return db.session.query(true()).filter(query.exists()).scalar()

from user import *  # noqa
from payment import *  # noqa
from ticket import *  # noqa
from cfp import *  # noqa

db.configure_mappers()
