"""
Pages under /organisation - this namespace is for information about EMF the organisation
rather than EMF the event.
"""

import json

from flask import render_template
from flask.typing import ResponseReturnValue

from apps.common import render_markdown

from . import base


@base.route("/organisation")
def organisation() -> ResponseReturnValue:
    return render_template("organisation/index.html")


@base.route("/organisation/finances")
def finances() -> ResponseReturnValue:
    return render_template("organisation/finances.html")


@base.route("/organisation/company")
def company() -> ResponseReturnValue:
    return render_markdown("organisation/company", page_name="company", template="organisation/template.html")


@base.route("/organisation/<page_name>")
def org_page(page_name: str) -> ResponseReturnValue:
    return render_markdown(
        f"organisation/{page_name}", page_name=page_name, template="organisation/template.html"
    )


@base.route("/organisation/diversity/<int:year>")
def yearly_diversity_stats(year: int) -> ResponseReturnValue:
    if year in (2018, 2022):
        with open(f"exports/{year}/public/UserDiversity.json") as raw_data:
            data = json.load(raw_data)

        return render_template(
            "about/diversity/pre-2024-stats.html",
            year=year,
            data=data["diversity"],
        )
    return render_markdown(f"about/diversity/{year}")
