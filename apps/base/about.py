from flask import render_template
from . import base

@base.route("/about")
def about():
    return render_template("about/index.html")


@base.route("/about/privacy")
def privacy():
    return render_template("about/privacy.html")


@base.route("/about/branding")
def branding():
    return render_template("branding.html")


@base.route("/about/design-elements")
def design_elements():
    return render_template("design.html")


@base.route("/about/company")
def company():
    return render_template("about/company.html")


@base.route("/about/volunteering")
def volunteering():
    return render_template("about/volunteering.html")


