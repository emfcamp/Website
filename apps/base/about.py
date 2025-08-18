"""
Pages under /about - content about the event.

Content about EMF the organisation should go in /organisation (organisation.py),
although some legacy content remains here.
"""

import json

from flask import (
    redirect,
    render_template,
    url_for,
)

from . import base
from apps.common import render_markdown


@base.route("/about/branding")
def branding():
    return render_template("about/branding.html")


@base.route("/about/<page_name>")
def page(page_name: str):
    return render_markdown(f"about/{page_name}", page_name=page_name)


@base.route("/about/diversity/<int:year>")
def yearly_diversity_stats(year: int):
    if year in (2018, 2022):
        with open(f"exports/{year}/public/UserDiversity.json", "r") as raw_data:
            data = json.load(raw_data)

        return render_template(
            f"about/diversity/pre-2024-stats.html",
            year=year,
            data=data["diversity"],
        )
    return render_markdown(f"about/diversity/{year}")


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
    return redirect(url_for(".page", page_name="health"), code=301)
