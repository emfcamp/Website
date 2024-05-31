"""
    Pages under /installations - the Installations programme
"""

from flask import render_template

from . import base
from apps.common import render_markdown


@base.route("/installations/<page_name>")
def installations_page(page_name: str):
    return render_markdown(f"installations/{page_name}", template="installations/template.html", page_name=page_name)

@base.route("/installations")
def installations():
    return render_template("installations/index.html")
