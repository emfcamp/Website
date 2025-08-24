"""
Tickets App

This handles users selecting tickets, entering their details, and choosing a payment method.
Users are then passed onto the appropriate view in the payment app to enter their payment
details.
"""

import re

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask import (
    current_app as app,
)
from flask_login import current_user, login_required
from flask_mailman import EmailMessage
from prometheus_client import Counter
from sqlalchemy.orm.exc import NoResultFound

from main import db, external_url
from models.basket import Basket
from models.product import ProductView
from models.purchase import Purchase, Ticket
from models.user import User, checkin_code_re

from ..common import (
    CURRENCY_SYMBOLS,
    feature_enabled,
    get_user_currency,
    set_user_currency,
)
from ..common.email import from_email
from ..common.receipt import (
    attach_tickets,
    make_qrfile,
    render_pdf,
    render_receipt,
    set_tickets_emailed,
)
from .forms import TicketTransferForm

tickets = Blueprint("tickets", __name__)

invalid_vouchers = Counter("emf_invalid_vouchers_total", "Invalid ticket vouchers")
no_capacity = Counter("emf_basket_no_capacity_total", "Attempted purchases that failed due to capacity")

price_changed = Counter(
    "emf_basket_price_changed_total",
    "Attempted purchases that failed due to changed prices",
)

empty_baskets = Counter("emf_basket_empty_total", "Attempted purchases of empty baskets")


@tickets.route("/tickets/reserved")
@tickets.route("/tickets/reserved/<currency>")
@tickets.route("/tickets/<flow>/reserved")
@tickets.route("/tickets/<flow>/reserved/<currency>")
def tickets_reserved(flow=None, currency=None):
    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".tickets_reserved", flow=flow)))

    basket = Basket(current_user, get_user_currency())
    basket.load_purchases_from_db()
    basket.save_to_session()

    if currency in CURRENCY_SYMBOLS:
        set_user_currency(currency)

    return redirect(url_for("tickets.pay", flow=flow))


@tickets.route("/tickets/<ticket_id>/transfer", methods=["GET", "POST"])
@login_required
def transfer(ticket_id):
    try:
        purchase = current_user.owned_purchases.filter_by(id=ticket_id).one()
    except NoResultFound:
        abort(404)

    if not purchase.is_paid_for:
        flash("Unpaid purchases cannot be transferred")
        return redirect(url_for("users.purchases"))

    if not purchase.product.get_attribute("is_transferable"):
        flash("This purchase cannot be transferred")
        return redirect(url_for("users.purchases"))

    form = TicketTransferForm()

    if form.validate_on_submit():
        email = form.email.data

        if not User.does_user_exist(email):
            new_user = True

            # Create a new user to transfer the ticket to
            to_user = User(email, form.name.data)
            db.session.add(to_user)
            db.session.commit()

        else:
            new_user = False
            to_user = User.get_by_email(email)

        purchase = Purchase.query.with_for_update().get(ticket_id)
        assert purchase.owner_id == current_user.id

        purchase.transfer(from_user=current_user, to_user=to_user)
        db.session.commit()

        app.logger.info("Purchase %s transferred from %s to %s", purchase, current_user, to_user)

        is_ticket = isinstance(purchase, Ticket)

        # Alert the users via email
        code = to_user.login_code(app.config["SECRET_KEY"])

        if is_ticket:
            subject = "You've been sent a ticket to Electromagnetic Field!"
        else:
            subject = "You've been sent an item from the Electromagnetic Field shop"

        msg = EmailMessage(
            subject,
            from_email=from_email("TICKETS_EMAIL"),
            to=[to_user.email],
        )

        already_emailed = set_tickets_emailed(to_user)
        msg.body = render_template(
            "emails/purchase-transfer-new-owner.txt",
            to_user=to_user,
            from_user=current_user,
            is_ticket=is_ticket,
            new_user=new_user,
            code=code,
            already_emailed=already_emailed,
        )

        if feature_enabled("ISSUE_TICKETS"):
            attach_tickets(msg, to_user)

        msg.send()
        db.session.commit()

        msg = EmailMessage(
            "Purchase transfer confirmation",
            from_email=from_email("TICKETS_EMAIL"),
            to=[current_user.email],
        )
        msg.body = render_template(
            "emails/purchase-transfer-original-owner.txt",
            to_user=to_user,
            from_user=current_user,
        )

        msg.send()

        flash("Your purchase was transferred.")
        return redirect(url_for("users.purchases"))

    return render_template("tickets/transfer.html", ticket=purchase, form=form)


@tickets.route("/tickets/receipt")
@tickets.route("/tickets/receipt.<format>")
@tickets.route("/tickets/<int:user_id>/receipt")
@tickets.route("/tickets/<int:user_id>/receipt.<format>")
@login_required
def receipt(user_id=None, format=None):
    if current_user.has_permission("admin") and user_id is not None:
        user = User.query.get(user_id)
    else:
        user = current_user

    if not user.owned_purchases.filter_by(is_paid_for=True).all():
        abort(404)

    png = bool(request.args.get("png"))
    pdf = False
    if format == "pdf":
        pdf = True

    page = render_receipt(user, png, pdf)
    if pdf:
        url = external_url("tickets.receipt", user_id=user_id)
        return send_file(render_pdf(url, page), mimetype="application/pdf", max_age=60)

    return page


# This used to be for xhtml2pdf, but is handy for creating a shareable image
@tickets.route("/receipt/<checkin_code>/qr")
def tickets_qrcode(checkin_code):
    if not re.match(f"{checkin_code_re}$", checkin_code):
        abort(404)

    url = app.config.get("CHECKIN_BASE") + checkin_code

    qrfile = make_qrfile(url, kind="png", scale=3)
    return send_file(qrfile, mimetype="image/png")


def get_product_view(flow):
    view = ProductView.get_by_name(flow)
    if not view:
        abort(404)
    return view


from . import tasks  # noqa
from . import choose  # noqa
from . import pay  # noqa
