"""Jinja2 extensions."""

from jinja2.ext import Extension
from markdown import markdown


class IncludemdExtension(Extension):
    def preprocess(self, source, name, filename=None):
        is_markdown = (filename and filename.endswith(".md")) or (name and name.endswith(".md"))
        if not is_markdown:
            return source
        return markdown(
            source,
            extensions=["markdown.extensions.nl2br"],
        )
