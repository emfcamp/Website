"""
Pages under /about - content about the event.

Content about EMF the organisation should go in /organisation (organisation.py),
although some legacy content remains here.
"""

from flask import (
    redirect,
    render_template,
    url_for,
)
from flask.typing import ResponseReturnValue

from apps.common import render_markdown

from . import base


@base.route("/supporting-emf")
def supporting_emf() -> ResponseReturnValue:
    return render_markdown("supporting-emf", template="markdown.html")


@base.route("/about/branding")
def branding() -> ResponseReturnValue:
    return render_template("about/branding.html")


@base.route("/about/<page_name>")
def page(page_name: str) -> ResponseReturnValue:
    return render_markdown(f"about/{page_name}", page_name=page_name)


# About and Contact have actual logic in them, so remain as HTML rather than
# markdown
@base.route("/about")
def about() -> ResponseReturnValue:
    return render_template("about/index.html")


@base.route("/about/contact")
def contact() -> ResponseReturnValue:
    return render_template("about/contact.html")


#### Redirects


@base.route("/about/covid")
def covid() -> ResponseReturnValue:
    return redirect(url_for(".page", page_name="health"), code=301)


@base.route("/about/diversity")
def about_diversity() -> ResponseReturnValue:
    return redirect(url_for(".org_page", page_name="diversity"))


@base.route("/about/diversity/<int:year>")
def yearly_diversity_stats_redirect(year: int) -> ResponseReturnValue:
    return redirect(url_for(".yearly_diversity_stats", year=year))


@base.route("/company")
def company_redirect() -> ResponseReturnValue:
    return redirect(url_for("base.company"))
