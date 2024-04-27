from flask import (
    render_template
)

from . import base

@base.route("/jobs")
def jobs_board():
    return render_template("jobs_board/index.html")
