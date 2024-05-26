"""
    Pages under /arcade - the arcade program.

    Content about EMF the organisation should go in /organisation (organisation.py),
    although some legacy content remains here.
"""

from flask import (
    abort,
    current_app as app,
    render_template,
    render_template_string,
)
from markdown import markdown
from os import path
from pathlib import Path

from markupsafe import Markup
from yaml import safe_load as parse_yaml
from . import base


def page_template(metadata):
    if "page_template" in metadata:
        return metadata["page_template"]

    if "show_nav" not in metadata or metadata["show_nav"] is True:
        return "arcade/template.html"
    else:
        return "static_page.html"


def render_markdown(source, **view_variables):
    template_root = Path(path.join(app.root_path, app.template_folder)).resolve()
    source_file = template_root.joinpath(f"{source}.md").resolve()

    if not source_file.is_relative_to(template_root) or not source_file.exists():
        return abort(404)

    with open(source_file, "r") as f:
        source = f.read()
        (metadata, content) = source.split("---", 2)
        metadata = parse_yaml(metadata)
        content = Markup(
            markdown(
                render_template_string(content),
                extensions=["markdown.extensions.nl2br"],
            )
        )

    view_variables.update(content=content, title=metadata["title"])
    return render_template(page_template(metadata), **view_variables)


@base.route("/arcade/<page_name>")
def arcade_page(page_name: str):
    return render_markdown(f"arcade/{page_name}", page_name=page_name)

@base.route("/arcade")
def arcade():
    return render_template("arcade/index.html")