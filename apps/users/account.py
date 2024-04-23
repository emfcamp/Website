from flask import render_template, redirect, request, flash, url_for, current_app as app
from flask_login import login_required, current_user
from wtforms import StringField, SubmitField, BooleanField
from wtforms.validators import DataRequired

from main import db
from models.purchase import Purchase
from models.payment import Payment
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


@users.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if get_site_state() == "cancelled":
        return redirect(url_for(".cancellation_refund"))

    if not current_user.diversity:
        flash(
            "Please check that your user details are correct. "
            "We'd also appreciate it if you could fill in our diversity survey."
        )
        return redirect(url_for(".details"))

    return render_template("account/main.html")


@users.route("/account/details", methods=["GET", "POST"])
@login_required
def details():
    form = AccountForm()

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
def purchases_redirect():
    return redirect(url_for(".purchases"))


@users.route("/account/purchases", methods=["GET", "POST"])
@login_required
def purchases():
    if get_site_state() == "cancelled":
        return redirect(url_for(".cancellation_refund"))

    purchases = current_user.owned_purchases.filter(
        ~Purchase.state.in_(["cancelled", "reserved", "admin-reserved"])
    ).order_by(Purchase.id)

    tickets = purchases.filter_by(is_ticket=True).all()
    other_items = purchases.filter_by(is_ticket=False).all()

    payments = (
        current_user.payments.filter(Payment.state != "cancelled")
        .order_by(Payment.state)
        .all()
    )

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
