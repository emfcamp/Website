"""
Pages under /code-of-conduct
"""

from flask.typing import ResponseValue

from apps.common import render_markdown

from . import base


# the CoC
@base.route("/code-of-conduct/")
def code_of_conduct() -> ResponseValue:
    return render_markdown("code-of-conduct/code-of-conduct", template="markdown.html")


# CoC transparency reports
#   if one doesnt exist for that year show the CoC instead
@base.route("/code-of-conduct/<int:year>")
def coc_transparency_report(year: int) -> ResponseValue:
    if year in (2024,):
        return render_markdown(f"code-of-conduct/{year}", template="markdown.html")
    return render_markdown("code-of-conduct/code-of-conduct", template="markdown.html")
