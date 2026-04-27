import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

import requests
from dateutil.parser import parse as parse_date
from flask import current_app as app
from flask import flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_required
from wtforms import BooleanField, StringField, SubmitField
from wtforms.validators import DataRequired

from main import db
from models.payment import Payment
from models.purchase import Purchase
from models.site_state import get_site_state

from ..common.forms import DiversityForm
from . import users


class AccountForm(DiversityForm):
    name = StringField("Name", [DataRequired()])
    allow_promo = BooleanField("Send me occasional emails about future EMF events")

    forward = SubmitField("Update")

    def update_user(self, user):
        user.name = self.name.data
        user.promo_opt_in = self.allow_promo.data

        return super().update_user(user)

    def set_from_user(self, user):
        # This is a required field so should always be set
        self.name.data = current_user.name
        self.allow_promo.data = current_user.promo_opt_in

        return super().set_from_user(user)


BLOG_POSTS: dict[str, Any] = {"timestamp": None, "posts": []}


def fetch_blog_posts():
    global BLOG_POSTS
    if BLOG_POSTS["timestamp"] is not None and BLOG_POSTS["timestamp"] > datetime.now() - timedelta(
        minutes=15
    ):
        return BLOG_POSTS["posts"]
    response = requests.get("https://blog.emfcamp.org/rss", timeout=1)
    if response.status_code != 200:
        return BLOG_POSTS["posts"]

    posts = []

    rss = ET.fromstring(response.text)
    for entry in rss.findall(".//{http://www.w3.org/2005/Atom}entry")[:3]:
        posts.append(
            {
                "title": entry.find("{http://www.w3.org/2005/Atom}title").text,
                "date": parse_date(entry.find("{http://www.w3.org/2005/Atom}published").text),
                "link": entry.find('{http://www.w3.org/2005/Atom}link[@type="text/html"]').attrib["href"],
            }
        )

    BLOG_POSTS = {"timestamp": datetime.now(), "posts": posts}
    return BLOG_POSTS["posts"]


@users.route("/account", methods=["GET", "POST"])
@login_required
def account() -> ResponseReturnValue:
    if get_site_state() == "cancelled":
        return redirect(url_for(".cancellation_refund"))

    if not current_user.diversity:
        flash(
            "Please check that your user details are correct. "
            "We'd also appreciate it if you could fill in our diversity survey."
        )
        return redirect(url_for(".details"))

    blog_posts = []
    try:
        blog_posts = fetch_blog_posts()
    except Exception:
        app.logger.exception("Error fetching blog posts")

    return render_template("account/main.html", blog_posts=blog_posts)


@users.route("/account/details", methods=["GET", "POST"])
@login_required
def details() -> ResponseReturnValue:
    form = AccountForm(user=current_user)

    if form.validate_on_submit():
        form.update_user(current_user)

        db.session.commit()
        app.logger.info("%s updated user information", current_user.name)

        flash("Your details have been saved.")
        return redirect(url_for(".account"))

    if request.method != "POST":
        form.set_from_user(current_user)

    return render_template("account/details.html", form=form)


@users.route("/account/tickets")
def purchases_redirect() -> ResponseReturnValue:
    return redirect(url_for(".purchases"))


@users.route("/account/purchases", methods=["GET", "POST"])
@login_required
def purchases() -> ResponseReturnValue:
    if get_site_state() == "cancelled":
        return redirect(url_for(".cancellation_refund"))

    purchases = current_user.owned_purchases.filter(
        ~Purchase.state.in_(["cancelled", "reserved", "admin-reserved"])
    ).order_by(Purchase.id)

    tickets = purchases.filter_by(is_ticket=True).all()
    other_items = purchases.filter_by(is_ticket=False).all()

    payments = current_user.payments.filter(Payment.state != "cancelled").order_by(Payment.state).all()

    if not tickets and not payments:
        return redirect(url_for("tickets.main"))

    transferred_to = current_user.transfers_to.all()
    transferred_from = current_user.transfers_from.all()

    show_receipt = any([t for t in tickets if t.is_paid_for is True])

    return render_template(
        "account/purchases.html",
        tickets=tickets,
        other_items=other_items,
        payments=payments,
        show_receipt=show_receipt,
        transferred_to=transferred_to,
        transferred_from=transferred_from,
    )


@users.route("/account/cancellation-refund")
@login_required
def cancellation_refund():
    payments = (
        current_user.payments.filter(~Payment.state.in_(("cancelled", "reserved", "admin-reserved")))
        .order_by(Payment.state)
        .all()
    )

    return render_template("account/cancellation-refund.html", payments=payments)
