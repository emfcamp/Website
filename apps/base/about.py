from flask import render_template
from . import base


@base.route("/about")
def about():
    return render_template("about/index.html")


@base.route("/about/travel")
def travel():
    return render_template("about/getting-there.html")


@base.route("/about/privacy")
def privacy():
    return render_template("about/privacy.html")


@base.route("/about/power")
def power():
    return render_template("about/power.html")


# @base.route("/about/internet")
# def internet():
#     return render_template("about/internet.html")


@base.route("/about/accessibility")
def accessibility():
    return render_template("about/accessibility.html")


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
