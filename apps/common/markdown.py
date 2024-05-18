from pathlib import Path

from markdown import markdown
from flask import (
    abort,
    current_app as app,
    render_template_string,
    render_template,
)
from markupsafe import Markup
from yaml import safe_load as parse_yaml


def page_template(metadata: dict) -> str:
    if "page_template" in metadata:
        return metadata["page_template"]

    if "show_nav" not in metadata or metadata["show_nav"] is True:
        return "about/template.html"
    else:
        return "static_page.html"


def markdown_content(raw_markdown: str) -> tuple[dict, Markup]:
    (metadata, content) = raw_markdown.split("---", 2)
    metadata_dict = parse_yaml(metadata)
    content = Markup(
        markdown(
            render_template_string(content),
            extensions=["markdown.extensions.nl2br"],
        )
    )
    return metadata_dict, content


def render_markdown_content(metadata: dict, content: Markup, **view_variables):
    view_variables.update(content=content, title=metadata["title"])
    return render_template(page_template(metadata), **view_variables)


def render_markdown(source: str, **view_variables):
    assert app.template_folder  # avoid mypy complaining this might be None
    template_root = Path(app.root_path).joinpath(app.template_folder).resolve()
    source_file = template_root.joinpath(f"{source}.md").resolve()

    if not source_file.is_relative_to(template_root) or not source_file.exists():
        return abort(404)

    with open(source_file, "r") as f:
        metadata, content = markdown_content(f.read())

    return render_markdown_content(metadata, content, **view_variables)
