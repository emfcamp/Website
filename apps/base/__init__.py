import os
from mailchimp3 import MailChimp
from mailchimp3.helpers import get_subscriber_hash
from mailchimp3.mailchimpclient import MailChimpError

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
from ..common import feature_flag
from models.product import Product, ProductView, ProductViewProduct, PriceTier
from models.site_state import get_site_state


base = Blueprint("base", __name__, cli_group=None)


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
    mc = MailChimp(mc_api=app.config["MAILCHIMP_KEY"])
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

        except MailChimpError as e:
            # Either the JSON, or a dictionary containing the response
            (data,) = e.args
            if data.get("status") != 400:
                raise

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
                    "Invalid Resource from MailChimp, likely bad email or rate limited: %r",
                    email,
                )
                flash(
                    """Your email address was not accepted - please check and try again.
                       If you've signed up to other lists recently, please wait 48 hours."""
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


@base.route("/network")
def network():
    return redirect("https://wiki.emfcamp.org/wiki/Network")


@base.route("/phones")
def phones():
    return redirect("https://wiki.emfcamp.org/wiki/Phones")


@base.route("/feedback")
def feedback():
    return render_template("feedback.html")


@base.route("/sponsors")
def sponsors():
    return abort(404)
    #  return render_template("sponsors/sponsors.html")


@base.route("/sponsor")
def sponsor():
    return render_template("sponsors/sponsor.html")


@base.route("/badge")
def badge():
    return redirect("https://wiki-archive.emfcamp.org/2012/wiki/TiLDA")


@base.route("/code-of-conduct")
def code_of_conduct():
    return render_template("code-of-conduct.html")


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


from . import redirects  # noqa
from . import about  # noqa
from . import organisation  # noqa
from . import scheduled_tasks  # noqa
from . import tasks_admin  # noqa
from . import tasks_banking  # noqa
from . import tasks_export  # noqa
from . import tasks_videos  # noqa
from . import dev  # noqa
