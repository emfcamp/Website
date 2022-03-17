"""
    Tickets App

    This handles users selecting tickets, entering their details, and choosing a payment method.
    Users are then passed onto the appropriate view in the payment app to enter their payment
    details.
"""

import re

from flask import (
    render_template,
    redirect,
    request,
    flash,
    Blueprint,
    url_for,
    send_file,
    abort,
    current_app as app,
)
from flask_login import login_required, current_user
from flask_mailman import EmailMessage
from prometheus_client import Counter
from sqlalchemy.orm.exc import NoResultFound

from main import db, external_url
from models.user import User, checkin_code_re
from models.product import ProductView
from models.basket import Basket
from models.purchase import Ticket

from ..common import (
    CURRENCY_SYMBOLS,
    get_user_currency,
    set_user_currency,
    feature_enabled,
)
from ..common.email import from_email
from ..common.receipt import (
    make_qr_png,
    make_barcode_png,
    render_pdf,
    render_receipt,
    attach_tickets,
    set_tickets_emailed,
)

from .forms import TicketTransferForm

tickets = Blueprint("tickets", __name__)

invalid_vouchers = Counter("emf_invalid_vouchers_total", "Invalid ticket vouchers")
no_capacity = Counter(
    "emf_basket_no_capacity_total", "Attempted purchases that failed due to capacity"
)

price_changed = Counter(
    "emf_basket_price_changed_total",
    "Attempted purchases that failed due to changed prices",
)

empty_baskets = Counter(
    "emf_basket_empty_total", "Attempted purchases of empty baskets"
)


@tickets.route("/tickets/reserved")
@tickets.route("/tickets/reserved/<currency>")
@tickets.route("/tickets/<flow>/reserved")
@tickets.route("/tickets/<flow>/reserved/<currency>")
def tickets_reserved(flow=None, currency=None):
    if current_user.is_anonymous:
        return redirect(
            url_for("users.login", next=url_for(".tickets_reserved", flow=flow))
        )

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
        ticket = current_user.owned_purchases.filter_by(id=ticket_id).one()
    except NoResultFound:
        abort(404)

    if not ticket.is_paid_for:
        flash("Unpaid tickets cannot be transferred")
        return redirect(url_for("users.purchases"))

    if not ticket.product.get_attribute("is_transferable"):
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

        ticket = Ticket.query.with_for_update().get(ticket_id)
        assert ticket.owner_id == current_user.id

        ticket.transfer(from_user=current_user, to_user=to_user)
        db.session.commit()

        app.logger.info(
            "Ticket %s transferred from %s to %s", ticket, current_user, to_user
        )

        # Alert the users via email
        code = to_user.login_code(app.config["SECRET_KEY"])

        msg = EmailMessage(
            "You've been sent a ticket to EMF!",
            from_email=from_email("TICKETS_EMAIL"),
            to=[to_user.email],
        )

        already_emailed = set_tickets_emailed(to_user)
        msg.body = render_template(
            "emails/ticket-transfer-new-owner.txt",
            to_user=to_user,
            from_user=current_user,
            new_user=new_user,
            code=code,
            already_emailed=already_emailed,
        )

        if feature_enabled("ISSUE_TICKETS"):
            attach_tickets(msg, to_user)

        msg.send()
        db.session.commit()

        msg = EmailMessage(
            "You sent someone an EMF ticket",
            from_email=from_email("TICKETS_EMAIL"),
            to=[current_user.email],
        )
        msg.body = render_template(
            "emails/ticket-transfer-original-owner.txt",
            to_user=to_user,
            from_user=current_user,
        )

        msg.send()

        flash("Your ticket was transferred.")
        return redirect(url_for("users.purchases"))

    return render_template("tickets/transfer.html", ticket=ticket, form=form)


@tickets.route("/tickets/receipt")
@tickets.route("/tickets/<int:user_id>/receipt")
@login_required
def receipt(user_id=None):
    if current_user.has_permission("admin") and user_id is not None:
        user = User.query.get(user_id)
    else:
        user = current_user

    if not user.owned_purchases.filter_by(is_paid_for=True).all():
        abort(404)

    png = bool(request.args.get("png"))
    pdf = bool(request.args.get("pdf"))

    page = render_receipt(user, png, pdf)
    if pdf:
        url = external_url("tickets.receipt", user_id=user_id)
        return send_file(
            render_pdf(url, page), mimetype="application/pdf", cache_timeout=60
        )

    return page


# Generate a PNG-based QR code as xhtml2pdf doesn't support SVG.
#
# This only accepts the code on purpose - we can't authenticate the
# user from the PDF renderer, and a full URL is awkward to validate.
@tickets.route("/receipt/<checkin_code>/qr")
def tickets_qrcode(checkin_code):
    if not re.match("%s$" % checkin_code_re, checkin_code):
        abort(404)

    url = app.config.get("CHECKIN_BASE") + checkin_code

    qrfile = make_qr_png(url)
    return send_file(qrfile, mimetype="image/png")


@tickets.route("/receipt/<checkin_code>/barcode")
def tickets_barcode(checkin_code):
    if not re.match("%s$" % checkin_code_re, checkin_code):
        abort(404)

    barcodefile = make_barcode_png(checkin_code)
    return send_file(barcodefile, mimetype="image/png")


def get_product_view(flow):
    view = ProductView.get_by_name(flow)
    if not view:
        abort(404)
    return view


from . import tasks  # noqa
from . import choose  # noqa
from . import pay  # noqa
