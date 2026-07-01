"""
Pages under /night-market
"""

from collections import defaultdict
from itertools import zip_longest
from pathlib import Path

from flask import abort, redirect, render_template, url_for
from flask.typing import ResponseReturnValue

from apps.common import MetaMarkdown, render_template_markdown
from main import cache

from ..config import config
from . import base


class Page(MetaMarkdown):
    def __repr__(self):
        return f"<Page {self.metadata.get('slug')}: {self.metadata.get('title')}>"


@base.route("/night-market")
def yearly_night_market_redirection() -> ResponseReturnValue:
    return redirect(url_for(".night_market", year=config.event_year))


@base.route("/night-market/<int:year>/<page_name>")
def night_market_page(year: int, page_name: str) -> ResponseReturnValue:
    pages = get_night_market_pages(year)
    if not pages:
        abort(404)

    return render_template_markdown(
        f"night-market/{year}/{page_name}.md",
        template=f"night-market/{year}/template.html",
        page_name=page_name,
        pages=pages,
        year=year,
    )


def get_days(pages: list[Page]) -> dict[str, list[Page]]:
    days = defaultdict(list)
    for page in pages:
        for day in page.metadata.get("days", []):
            days[day].append(page)
    return days


@cache.memoize(timeout=10)
def get_night_market_pages(year: int) -> list[Page]:
    md_dir = Path(f"templates/night-market/{year}")
    if not md_dir.is_dir():
        return []
    pages = []
    for md in md_dir.glob("*.md"):
        page = Page(md.read_text())
        slug = md.stem
        page.metadata.setdefault("slug", slug)
        pages.append(page)
    pages.sort(key=lambda p: p.metadata.get("title", ""))
    return pages


@base.route("/night-market/<int:year>")
def night_market(year: int) -> ResponseReturnValue:
    pages = get_night_market_pages(year)
    days = get_days(pages)
    days_table = list(zip_longest(days["friday"], days["saturday"], days["sunday"]))

    return render_template(
        f"night-market/{year}/index.html",
        pages=pages,
        days_table=days_table,
        year=year,
    )
