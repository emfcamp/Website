"""
Pages under /installations - the Installations programme
"""

from flask import redirect, render_template, url_for

from apps.common import render_markdown
from models import event_year

from . import base


@base.route("/installations")
def yearly_installation_redirection():
    return redirect(url_for(".installations", year=event_year()))


@base.route("/installations/<int:year>/<page_name>")
def installations_page(year: int, page_name: str):
    return render_markdown(
        f"installations/{year}/{page_name}",
        template=f"installations/{year}/template.html",
        page_name=page_name,
    )


@base.route("/installations/<int:year>")
def installations(year: int):
    return render_template(f"installations/{year}/main.html")
