""" Call for Participation app """
from flask import Blueprint

cfp = Blueprint("cfp", __name__)

from . import views  # noqa
from . import tasks  # noqa
from . import schedule_tasks  # noqa
from . import event_tickets_lottery  # noqa: F401
