"""
Wiki App

Collaboratively editable wiki pages with version history.
"""

from flask import Blueprint

wiki = Blueprint("wiki", __name__)

from . import views  # noqa: F401, E402
