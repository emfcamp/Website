""" This module contains code, mostly CLI tasks specific to development,
    such as for generating fake data.
"""
from flask.cli import AppGroup
from .. import base

dev_cli = AppGroup("dev")
base.cli.add_command(dev_cli)

from . import tasks  # noqa
