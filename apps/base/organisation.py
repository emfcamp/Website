"""
    Pages under /organisation - this namespace is for information about EMF the organisation
    rather than EMF the event.
"""
from flask import render_template
from . import base


@base.route("/organisation/finances")
def finances():
    return render_template("organisation/finances.html")
