"""
Pages under /installations - the Installations programme
"""

from flask import redirect, render_template, url_for
from flask.typing import ResponseReturnValue

from apps.common import render_template_markdown

from ..config import config
from . import base


@base.route("/installations")
def yearly_installation_redirection() -> ResponseReturnValue:
    return redirect(url_for(".installations", year=config.event_year))


@base.route("/installations/<int:year>/<page_name>")
def installations_page(year: int, page_name: str) -> ResponseReturnValue:
    return render_template_markdown(
        f"installations/{year}/{page_name}.md",
        template=f"installations/{year}/template.html",
        page_name=page_name,
    )


@base.route("/installations/<int:year>")
def installations(year: int) -> ResponseReturnValue:
    return render_template(f"installations/{year}/main.html")
