"""
    Pages under /about - content about the event.

    Content about EMF the organisation should go in /organisation (organisation.py),
    although some legacy content remains here.
"""

from flask import (
    abort,
    current_app as app,
    redirect,
    render_template,
    render_template_string,
    url_for,
)
from markdown import markdown
from os import path
from pathlib import Path

from markupsafe import Markup
from yaml import safe_load as parse_yaml
from . import base


def page_template(metadata):
    if "show_nav" not in metadata or metadata["show_nav"] is True:
        return "about/template.html"
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


@base.route("/about/branding")
def branding():
    return render_template("about/branding.html")


@base.route("/about/<page_name>")
def page(page_name: str):
    return render_markdown(f"about/{page_name}", page_name=page_name)


# About and Contact have actual logic in them, so remain as HTML rather than
# markdown
@base.route("/about")
def about():
    return render_template("about/index.html")


@base.route("/company")
def company():
    return render_markdown("about/company")


@base.route("/about/contact")
def contact():
    return render_template("about/contact.html")


@base.route("/about/covid")
def covid():
    return redirect(url_for(".health"))
