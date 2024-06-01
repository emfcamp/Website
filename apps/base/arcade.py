"""
    Pages under /arcade - the arcade program.
"""

from flask import render_template, redirect, url_for

from . import base
from models import event_year
from apps.common import render_markdown


@base.route("/arcade")
def yearly_arcade_redirection():
    return redirect(url_for('.arcade', year=event_year()))

@base.route("/arcade/<int:year>/<page_name>")
def arcade_page(year: int, page_name: str):
    return render_markdown(f"arcade/{year}/{page_name}", template=f"arcade/{year}/template.html", page_name=page_name)

@base.route("/arcade/<int:year>")
def arcade(year: int):
    return render_template(f"arcade/{year}/main.html")

