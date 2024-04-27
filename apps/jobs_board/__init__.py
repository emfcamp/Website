from flask import (
    render_template,
    Blueprint,
)

jobs_board = Blueprint("jobs_board", __name__)

@jobs_board.route("/")
def main():
    return render_template("jobs_board/index.html")
