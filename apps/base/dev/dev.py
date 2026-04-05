from flask import (
    Blueprint,
    render_template,
)
from flask.typing import ResponseReturnValue

from apps.common import render_markdown

dev = Blueprint("dev", __name__)


@dev.route("/design/main")
def design_main() -> ResponseReturnValue:
    return render_template("dev/design.html")


@dev.route("/design/markdown")
def design_markdown() -> ResponseReturnValue:
    return render_markdown("dev/design", template="markdown.html")
