import os
from typing import Optional

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
from flask_login import current_user
import requests

from main import cache
from models.product import Price, Product, ProductView, ProductViewProduct, PriceTier
from models.site_state import get_site_state


base = Blueprint("base", __name__, cli_group=None)


@cache.cached(timeout=60, key_prefix="get_full_price")
def get_full_price() -> Optional[Price]:
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

    # Send ticketholders to the account page.
    if (
        state in ("sales", "event")
        and current_user.is_authenticated
        and len(list(current_user.get_owned_tickets(True))) > 0
    ):
        return redirect(url_for("users.account"))

    return render_template("home/%s.html" % state, full_price=get_full_price())


@base.route("/", methods=["POST"])
def main_post():
    honeypot_field = request.form.get("name")
    email = request.form.get("email", "").strip()
    list = request.form.get("list")

    if request.form.get("list") not in app.config["LISTMONK_LISTS"]:
        return raise_404()

    if email == "":
        return redirect(url_for(".main"))

    if honeypot_field != "":
        app.logger.warn(
            "Mailing list honeypot field failed for %s (IP %s)",
            email,
            request.remote_addr,
        )
        flash("We aren't able to subscribe you at this time.")
        return redirect(url_for(".main"))

    response = requests.post(
        app.config["LISTMONK_URL"] + "/api/public/subscription",
        json={"email": email, "list_uuids": [app.config["LISTMONK_LISTS"][list]]},
    )

    if response.status_code != 200:
        app.logger.warn(
            "Unable to subscribe to mailing list (HTTP %s): %s",
            response.status_code,
            response.text,
        )
        flash("Sorry, we were unable to subscribe you to the mailing list. Please try again later.")

    else:
        flash(
            "Thanks for subscribing! If you weren't already subscribed, you will receive a confirmation email shortly."
        )

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
    return redirect("/about/internet")


@base.route("/phones")
def phones():
    return redirect("/about/phones")


@base.route("/feedback")
def feedback():
    return render_template("feedback.html")


@base.route("/sponsors")
def sponsors():
    # return abort(404)
    return render_template("sponsors/sponsors.html")


@base.route("/sponsor")
def sponsor():
    return render_template("sponsors/sponsor.html")


@base.route("/badge")
def badge():
    return redirect("https://tildagon.badge.emfcamp.org/")


@base.route("/code-of-conduct")
def code_of_conduct():
    return render_template("code-of-conduct.html")


@base.route("/googlec108e6ab4f75019d.html")
def google_verification_russ():
    return "google-site-verification: googlec108e6ab4f75019d.html"


@base.route("/google3189d9169f2faf7f.html")
def google_verification_mark():
    return "google-site-verification: google3189d9169f2faf7f.html"


@base.route("/.well-known/security.txt")
def security_txt():
    return """Contact: security@emfcamp.org\n"""


@base.route("/.well-known/matrix/server")
def matrix_server():
    return {"m.server": "matrix.emfcamp.org:443"}


@base.route("/.well-known/matrix/client")
def matrix_client():
    return {"m.homeserver": {"base_url": "https://matrix.emfcamp.org"}}


@base.route("/subscribe")
def subscribe():
    return render_template("subscribe.html")


@base.route("/emp")
def emp():
    return render_template("emp.html")


@base.route("/deliveries")
def deliveries():
    return redirect("/static/deliveries.pdf")


from . import redirects  # noqa
from . import about  # noqa
from . import organisation  # noqa
from . import scheduled_tasks  # noqa
from . import tasks_admin  # noqa
from . import tasks_banking  # noqa
from . import tasks_export  # noqa
from . import tasks_videos  # noqa
from . import dev  # noqa
