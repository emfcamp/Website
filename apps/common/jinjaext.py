"""Jinja2 extensions."""

from typing import ClassVar

from jinja2.ext import Extension
from jinja2.nodes import Const, ContextReference, Output
from jinja2.parser import Parser
from jinja2.runtime import Context
from markupsafe import Markup

from . import render_trusted_markdown


class IncludemdExtension(Extension):
    """Adds a `include_markdown` tag to Jinja that works like 'include' but for
    Markdown."""

    tags: ClassVar[set[str]] = {"include_markdown"}  # type: ignore[misc]

    def parse(self, parser: Parser) -> Output:
        lineno = next(parser.stream).lineno
        template_name = parser.parse_expression()
        parent_template_name = Const(parser.name)
        args = [template_name, parent_template_name, ContextReference()]
        call = self.call_method("_render_markdown", args, lineno=lineno)
        return Output([call], lineno=lineno)

    def _render_markdown(self, template_name: str, parent_template_name: str, context: Context) -> Markup:
        template = self.environment.get_template(template_name, parent_template_name)
        gen = template.root_render_func(template.new_context(context.get_all(), True))
        value = self.environment.concat(gen)
        return render_trusted_markdown(value)
