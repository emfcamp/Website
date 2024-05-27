"""
    Pages under /arcade - the arcade program.
"""

from flask import render_template

from . import base
from apps.common import render_markdown


@base.route("/arcade/<page_name>")
def arcade_page(page_name: str):
    return render_markdown(f"arcade/{page_name}", template="arcade/template.html", page_name=page_name)

@base.route("/arcade")
def arcade():
    return render_template("arcade/index.html")

