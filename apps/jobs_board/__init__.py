import json

from flask import (
    render_template,
    Blueprint,
)

jobs_board = Blueprint("jobs_board", __name__)

@jobs_board.route("/")
def main():
    with open('apps/jobs_board/jobs.json', 'r') as file:
        jobs = json.load(file)
        return render_template("jobs_board/index.html", jobs=jobs)
