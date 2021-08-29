"""
    Pages under /about - content about the event.

    Content about EMF the organisation should go in /organisation (organisation.py),
    although some legacy content remains here.
"""

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


@base.route("/about/childcare")
def childcare():
    return render_template("about/childcare.html")


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


@base.route("/about/what_to_bring")
def what_to_bring():
    return render_template("about/what-to-bring.html")


@base.route("/about/food")
def food():
    return render_template("about/food.html")


@base.route("/about/contact")
def contact():
    return render_template("about/contact.html")
