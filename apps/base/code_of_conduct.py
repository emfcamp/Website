"""
Pages under /code-of-conduct
"""

from flask.typing import ResponseReturnValue

from apps.common import render_template_markdown

from . import base


# the CoC
@base.route("/code-of-conduct/")
def code_of_conduct() -> ResponseReturnValue:
    return render_template_markdown("code-of-conduct/code-of-conduct.md", template="markdown.html")


# CoC transparency reports
#   if one doesnt exist for that year show the CoC instead
@base.route("/code-of-conduct/<int:year>")
def coc_transparency_report(year: int) -> ResponseReturnValue:
    if year in {2024}:
        return render_template_markdown(f"code-of-conduct/{year}.md", template="markdown.html")
    return render_template_markdown("code-of-conduct/code-of-conduct.md", template="markdown.html")
