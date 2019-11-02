import os
import csv
import json
from mailchimp3 import MailChimp
from mailchimp3.helpers import get_subscriber_hash
from requests import HTTPError

from flask import (
    render_template,
    redirect,
    request,
    flash,
    Blueprint,
    url_for,
    send_from_directory,
    abort,
    current_app as app,
)

from main import cache
from .common import feature_flag
from models.product import Product, ProductView, ProductViewProduct, PriceTier
from models.site_state import get_site_state


base = Blueprint("base", __name__)


@cache.cached(timeout=60, key_prefix="get_full_price")
def get_full_price():
    full = (
        ProductView.query.filter_by(name="main")
        .join(ProductViewProduct, Product, PriceTier)
        .filter_by(active=True)
        .order_by(ProductViewProduct.order)
        .with_entities(PriceTier)
        .first()
    )

    if full is not None:
        return full.get_price("GBP")

    return None


@base.route("/")
def main():
    state = get_site_state()
    if app.config.get("DEBUG"):
        state = request.args.get("site_state", state)

    return render_template("home/%s.html" % state, full_price=get_full_price())


@base.route("/", methods=["POST"])
def main_post():
    # mc_user will be removed in v2.1.0
    mc = MailChimp(mc_secret=app.config["MAILCHIMP_KEY"], mc_user="python-mailchimp")
    try:
        email = request.form.get("email")

        try:
            data = mc.lists.members.create_or_update(
                list_id=app.config["MAILCHIMP_LIST"],
                subscriber_hash=get_subscriber_hash(email),
                data={
                    "email_address": email,
                    "status": "subscribed",
                    "status_if_new": "pending",
                },
            )
            status = data.get("status")
            if status == "pending":
                flash(
                    "Thanks for subscribing! You will receive a confirmation email shortly."
                )
            elif status == "subscribed":
                flash("You were already subscribed! Thanks for checking back.")
            else:
                raise ValueError("Unexpected status %s" % status)

        except ValueError as e:
            # ugh, this library is awful
            app.logger.info(
                "ValueError from mailchimp3 %s, assuming bad email: %r", e, email
            )
            flash("Your email address was not accepted - please check and try again.")

        # should also be changed to exceptions in v2.1.0
        except HTTPError as e:
            if e.response.status_code != 400:
                raise

            data = e.response.json()
            title = data.get("title")
            if title == "Member In Compliance State":
                app.logger.info("Member in compliance state: %r", email)
                flash(
                    """You've already been unsubscribed from our list, so we can't add you again.
                         Please contact %s to update your settings."""
                    % app.config["TICKETS_EMAIL"][1]
                )

            elif title == "Invalid Resource":
                app.logger.warn(
                    "Invalid Resource from MailChimp, assuming bad email: %r", email
                )
                flash(
                    "Your email address was not accepted - please check and try again."
                )

            else:
                app.logger.warn("MailChimp returned %s: %s", title, data.get("detail"))
                flash("Sorry, an error occurred: %s." % (title or "unknown"))

    except Exception as e:
        app.logger.error("Error subscribing: %r", e)
        flash("Sorry, an error occurred.")

    return redirect(url_for(".main"))


@base.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static/images"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


@base.route("/404")
def raise_404():
    abort(404)


@base.route("/500")
def raise_500():
    abort(500)


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


@base.route("/network")
def network():
    return redirect("https://wiki.emfcamp.org/wiki/Network")


@base.route("/phones")
def phones():
    return redirect("https://wiki.emfcamp.org/wiki/Phones")


@base.route("/feedback")
def feedback():
    return render_template("feedback.html")


@base.route("/talks")
@base.route("/talks/")
def talks():
    return redirect(url_for("schedule.line_up"))


@base.route("/line-up/2016")
@base.route("/talks/2016")
def talks_2016():
    talk_path = os.path.abspath(
        os.path.join(__file__, "..", "..", "exports", "2016", "public")
    )
    data = json.load(open(os.path.join(talk_path, "schedule.json"), "r"))

    stage_venues = ["Stage A", "Stage B", "Stage C"]
    workshop_venues = ["Workshop 1", "Workshop 2", "Workshop 3"]

    stage_events = []
    workshop_events = []

    for event in data:
        if event["source"] == "external":
            continue

        # Hack to remove Stitch's "hilarious" failed <script>
        if "<script>" in event["speaker"]:
            event["speaker"] = event["speaker"][
                0 : event["speaker"].find("<script>")
            ]  # "Some idiot"

        # All official (non-external) content is on a stage or workshop, so we don't care about anything that isn't
        if event["venue"] in stage_venues:
            events_list = stage_events
        elif event["venue"] in workshop_venues:
            events_list = workshop_events
        else:
            continue

        # Make sure it's not already in the list (basically repeated workshops)
        if not any(e["title"] == event["title"] for e in events_list):
            events_list.append(event)

    # Sort should avoid leading punctuation and whitespace and be case-insensitive
    stage_events.sort(key=lambda event: event["title"].strip().strip("'").upper())
    workshop_events.sort(key=lambda event: event["title"].strip().strip("'").upper())

    venues = [
        {"name": "Main Stages", "events": stage_events},
        {"name": "Workshops", "events": workshop_events},
    ]

    return render_template("talks-2016.html", venues=venues)


@base.route("/line-up/2014")
@base.route("/talks/2014")
def talks_2014():
    talks = []
    talk_path = os.path.abspath(os.path.join(__file__, "..", "..", "talks", "2014"))
    data = json.load(open(os.path.join(talk_path, "events.json"), "r"))
    for event in data["conference_events"]["events"]:
        if event["type"] not in ("lecture", "workshop", "other"):
            continue
        talks.append(
            (
                ", ".join(
                    map(lambda speaker: speaker["full_public_name"], event["speakers"])
                ),
                event["title"],
                event["abstract"],
            )
        )

    return render_template("talks-2014.html", talks=talks)


@base.route("/line-up/2012")
@base.route("/talks/2012")
def talks_2012():
    days = {}
    talk_path = os.path.abspath(os.path.join(__file__, "..", "..", "talks", "2012"))
    for day in ("friday", "saturday", "sunday"):
        reader = csv.reader(open(os.path.join(talk_path, "%s.csv" % day), "r"))
        rows = []
        for row in reader:
            cells = ["" if c == '"' else c for c in row]
            app.logger.debug(cells)
            rows.append(cells)

        days[day] = rows

    return render_template("talks-2012.html", **days)


@base.route("/sponsors")
def sponsors():
    return render_template("sponsors/sponsors.html")


@base.route("/sponsor")
def sponsor():
    return render_template("sponsors/sponsor.html")


@base.route("/participating")
@base.route("/get_involved")
@base.route("/contact")
@base.route("/location")
@base.route("/about")
def old_urls_2012():
    return redirect(url_for(".main"))


@base.route("/badge")
def badge():
    return redirect("https://wiki-archive.emfcamp.org/2012/wiki/TiLDA")


@base.route("/code-of-conduct")
def code_of_conduct():
    return render_template("code-of-conduct.html")


@base.route("/diversity")
def diversity():
    return render_template("diversity.html")


@base.route("/wave")
def wave():
    return redirect(
        "https://web.archive.org/web/20130627201413/https://www.emfcamp.org/wave"
    )


@base.route("/wave-talks")
@base.route("/wave/talks")
def wave_talks():
    return redirect(
        "https://web.archive.org/web/20130627201413/https://www.emfcamp.org/wave/talks"
    )


@base.route("/sine")
@base.route("/wave/sine")
@base.route("/wave/SiNE")
def sine():
    return redirect("https://wiki-archive.emfcamp.org/2014/wiki/SiNE")


@base.route("/radio", methods=["GET"])
@feature_flag("RADIO")
def radio():
    return render_template("radio.html")


@base.route("/googlec108e6ab4f75019d.html")
def google_verification_russ():
    return "google-site-verification: googlec108e6ab4f75019d.html"


@base.route("/google3189d9169f2faf7f.html")
def google_verification_mark():
    return "google-site-verification: google3189d9169f2faf7f.html"


@base.route("/.well-known/security.txt")
def security_txt():
    return """Contact: security@emfcamp.org\n"""


@base.route("/herald")
def herald():
    return redirect("https://wiki.emfcamp.org/wiki/Herald")


@base.route("/subscribe")
def subscribe():
    return render_template("subscribe.html")


@base.route("/emp")
def emp():
    return render_template("emp.html")
