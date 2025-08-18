from decorator import decorator
from collections import OrderedDict
import re

from flask import (
    render_template,
    redirect,
    request,
    flash,
    url_for,
    session,
    current_app as app,
    g,
    Blueprint,
    abort,
    render_template_string,
)
from markupsafe import Markup
from flask_login import current_user
from sqlalchemy import func

from main import db
from models.arrivals import ArrivalsView
from models.permission import Permission
from models.purchase import Purchase, CheckinStateException
from models.user import User, checkin_code_re
from .common import json_response

arrivals = Blueprint("arrivals", __name__)


@decorator
def arrivals_required(f, *args, **kwargs):
    if not current_user.is_authenticated:
        return app.login_manager.unauthorized()

    # If we have an arrivals_view, ensure they're authorised for it.
    view_name = session.get("arrivals_view")
    view = None
    if view_name:
        view = ArrivalsView.get_by_name(view_name)
        if view:
            if not current_user.has_permission(view.required_permission.name):
                # User has an arrivals_view, but they don't have permission.
                abort(403)
        else:
            app.logger.warning('User had invalid "arrivals_view" in their session: %s', view_name)
            del session["arrivals_view"]
            view_name = view = None

    if current_user.has_permission("admin"):
        views = ArrivalsView.query.all()
    else:
        views = (
            ArrivalsView.query.join(ArrivalsView.required_permission)
            .join(Permission.user)
            .where(User.id == current_user.id)
            .all()
        )
    if not views:
        abort(404)
    g.arrivals_views = views
    if not view:
        view = views[0]
    session["arrivals_view"] = view.name
    g.arrivals_view = view
    return f(*args, **kwargs)


@arrivals.route("/")
@arrivals_required
def main():
    return render_template("arrivals/arrivals.html", view=g.arrivals_view, views=g.arrivals_views)


@arrivals.route("/arrivals/view/<view>")
@arrivals_required
def change_arrivals_view(view):
    session["arrivals_view"] = view
    return redirect(url_for(".main"))


# Entrypoint for QR code
@arrivals.route("/arrivals/qrcode/<code>")
@arrivals_required
def checkin_qrcode(code):
    match = re.match("%s$" % checkin_code_re, code)
    if not match:
        abort(404)

    user = User.get_by_checkin_code(app.config.get("SECRET_KEY"), code)
    return redirect(url_for(".checkin", user_id=user.id, source="code"))


def user_from_code(query):
    if not query:
        return None

    # QR code
    match = re.match(re.escape(app.config.get("CHECKIN_BASE")) + "(%s)$" % checkin_code_re, query)
    if not match:
        return None

    code = match.group(1)
    user = User.get_by_checkin_code(app.config.get("SECRET_KEY"), code)
    return user


def users_from_query(query):
    names = User.query.order_by(User.name)
    emails = User.query.order_by(User.email)

    def escape(like):
        return like.replace("^", "^^").replace("%", "^%")

    def name_match(pattern, query):
        return names.filter(User.name.ilike(pattern.format(query), escape="^")).limit(10).all()

    def email_match(pattern, query):
        return emails.filter(User.email.ilike(pattern.format(query), escape="^")).limit(10).all()

    fulls = []
    starts = []
    contains = []
    query = query.lower()
    words = list(map(escape, filter(None, query.split(" "))))

    if " " in query:
        fulls += name_match("%{0}%", "%".join(words))
        fulls += email_match("%{0}%", "%".join(words))

    for word in words:
        starts += name_match("{0}%", word)
        contains += name_match("%{0}%", word)

    for word in words:
        starts += email_match("{0}%", word)
        contains += email_match("%{0}%", word)

    # make unique, but keep in order
    users = list(OrderedDict.fromkeys(fulls + starts + contains))[:10]
    return users


@arrivals.route("/search", methods=["GET", "POST"])
@arrivals.route("/search/<query>")  # debug only
@json_response
@arrivals_required
def search(query=None):
    if not (app.config.get("DEBUG") and query):
        query = request.form.get("q")

    if query.startswith("fail"):
        raise ValueError("User-requested failure: %s" % query)

    if not query:
        abort(404)

    data = {}
    if request.form.get("n"):
        # To serialise requests as they may go slow for certain query strings
        data["n"] = int(request.form.get("n"))

    query = query.strip()
    user = user_from_code(query)

    if user:
        return {"location": url_for(".checkin", user_id=user.id, source="code")}

    users_ordered = users_from_query(query)
    users = User.query.filter(User.id.in_([u.id for u in users_ordered]))

    product_ids = [p.id for p in g.arrivals_view.products]
    purchases = (
        users.join(User.owned_purchases)
        .filter_by(is_paid_for=True)
        .filter(Purchase.product_id.in_(product_ids))
        .group_by(User.id)
        .with_entities(User.id, func.count(User.id))
    )
    purchases = dict(purchases)

    completes = (
        users.join(User.owned_purchases)
        .filter_by(is_paid_for=True)
        .filter_by(redeemed=True)
        .filter(Purchase.product_id.in_(product_ids))
    )

    completes = completes.group_by(User).with_entities(User.id, func.count(User.id))
    completes = dict(completes)

    user_data = []
    for u in users:
        user = {
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "purchases": purchases.get(u.id, 0),
            "completes": completes.get(u.id, 0),
            "url": url_for(".checkin", user_id=u.id, source="typed"),
        }
        user_data.append(user)

    data["users"] = user_data

    return data


@arrivals.route("/arrivals/<int:user_id>", methods=["GET", "POST"])
@arrivals.route("/arrivals/<int:user_id>/<source>", methods=["GET", "POST"])
@arrivals_required
def checkin(user_id, source=None):
    user = User.query.get_or_404(user_id)

    if source not in {None, "typed", "transfer", "code"}:
        abort(404)

    product_ids = [p.id for p in g.arrivals_view.products]
    purchases = (
        user.owned_purchases.filter(Purchase.product_id.in_(product_ids))
        .filter_by(is_paid_for=True)
        .order_by(Purchase.id)
        .all()
    )
    other_purchases = (
        user.owned_purchases.filter(Purchase.product_id.not_in(product_ids))
        .filter_by(is_paid_for=True)
        .order_by(Purchase.id)
        .all()
    )

    if request.method == "POST":
        failed = []
        for p in purchases:
            # Only allow bulk completion, not undoing
            try:
                p.redeem()
            except CheckinStateException:
                failed.append(p)

        db.session.commit()

        if failed:
            failed_str = ", ".join(str(p.id) for p in failed)
            success_count = len(purchases) - len(failed)
            flash("Checked in %s purchases. Already checked in: %s" % (success_count, failed_str))

            return redirect(url_for(".checkin", user_id=user.id))

        msg = Markup(
            render_template_string(
                """
            {{ purchases|count }} purchase {{- purchases|count != 1 and 's' or '' }} checked in.
            <a class="alert-link" href="{{ url_for('.checkin', user_id=user.id) }}">Show purchases</a>.""",
                user=user,
                purchases=purchases,
            )
        )
        flash(msg)

        return redirect(url_for(".main"))

    transferred_purchases = [
        t.purchase for t in user.transfers_from.join(Purchase).filter(Purchase.product_id.in_(product_ids))
    ]

    return render_template(
        "arrivals/checkin.html",
        view=g.arrivals_view,
        views=g.arrivals_views,
        user=user,
        purchases=purchases,
        other_purchases=other_purchases,
        transferred_purchases=transferred_purchases,
        source=source,
    )


@arrivals.route("/arrivals/purchase/<purchase_id>", methods=["POST"])
@arrivals_required
def redeem_purchase(purchase_id):
    purchase = Purchase.query.get_or_404(purchase_id)
    if not purchase.is_paid_for:
        abort(404)

    try:
        purchase.redeem()
    except CheckinStateException as e:
        flash(str(e))

    db.session.commit()
    flash(f"Redeemed {purchase.product.display_name} owned by {purchase.owner.name}")

    back = int(request.args.get("back", purchase.owner.id))
    return redirect(url_for(".checkin", user_id=back))


@arrivals.route("/arrivals/purchase/<purchase_id>/undo", methods=["POST"])
@arrivals_required
def unredeem_purchase(purchase_id):
    purchase = Purchase.query.get_or_404(purchase_id)
    if not purchase.is_paid_for:
        abort(404)

    try:
        purchase.unredeem()
    except CheckinStateException as e:
        flash(str(e))

    db.session.commit()
    flash(f"Undid redemption of {purchase.product.display_name} owned by {purchase.owner.name}")

    back = int(request.args.get("back", purchase.owner.id))
    return redirect(url_for(".checkin", user_id=back))
