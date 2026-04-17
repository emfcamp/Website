"""
Pages under /arcade - the arcade program.
"""

from flask import redirect, render_template, url_for
from flask.typing import ResponseReturnValue

from apps.common import render_template_markdown

from ..config import config
from . import base


@base.route("/arcade")
def yearly_arcade_redirection() -> ResponseReturnValue:
    return redirect(url_for(".arcade", year=config.event_year))


@base.route("/arcade/<int:year>/<page_name>")
def arcade_page(year: int, page_name: str) -> ResponseReturnValue:
    return render_template_markdown(
        f"arcade/{year}/{page_name}.md", template=f"arcade/{year}/template.html", page_name=page_name
    )


@base.route("/arcade/<int:year>")
def arcade(year: int) -> ResponseReturnValue:
    return render_template(f"arcade/{year}/main.html")
