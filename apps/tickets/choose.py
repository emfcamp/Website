from collections import OrderedDict

from flask import (
    render_template,
    redirect,
    request,
    flash,
    url_for,
    session,
    abort,
    current_app as app,
)
from flask_login import current_user
from flask_mail import Message
from sqlalchemy.orm import joinedload

from main import db, mail
from models.exc import CapacityException
from models.product import PriceTier, ProductView, ProductViewProduct, Product, Voucher
from models.basket import Basket
from models.site_state import get_sales_state

from ..common import get_user_currency, set_user_currency, feature_enabled
from ..common.receipt import attach_tickets, set_tickets_emailed

from .forms import TicketAmountsForm
from . import tickets, empty_baskets, no_capacity, invalid_vouchers


@tickets.route("/tickets", methods=["GET", "POST"])
@tickets.route("/tickets/<flow>", methods=["GET", "POST"])
def main(flow=None):
    """ The main tickets page. This lets the user choose which tickets to buy,
        creates a basket for them and then adds the tickets to their basket.

        At this point tickets are reserved, and the user is passed on to `/tickets/pay`
        to enter their user details and choose a payment method.

        The `flow` parameter dictates which ProductView to display on this page,
        and allows us to have different categories of items on sale, for example tickets
        on one page, and t-shirts on a separate page.
    """
    if flow is None:
        flow = "main"

    # For now, use the flow name as a view name. This might change.
    view = ProductView.get_by_name(flow)
    if not view:
        abort(404)

    if view.cfp_accepted_only and current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".main", flow=flow)))

    if not view.is_accessible(current_user, session.get("ticket_voucher")):
        abort(404)

    sales_state = get_sales_state()

    if sales_state in ["unavailable", "sold-out"]:
        # For the main entry point, we assume people want admissions tickets,
        # but we still need to sell people parking tickets, tents or tickets
        # from vouchers until the final cutoff (sales-ended).
        if flow != "main":
            sales_state = "available"

    if app.config.get("DEBUG"):
        sales_state = request.args.get("sales_state", sales_state)

    if sales_state in {"available", "unavailable"}:
        pass
    elif not current_user.is_anonymous and current_user.has_permission("admin"):
        pass
    else:
        return render_template("tickets/cutoff.html")

    tiers = OrderedDict()
    products = (
        ProductViewProduct.query.filter_by(view_id=view.id)
        .join(ProductViewProduct.product)
        .with_entities(Product)
        .order_by(ProductViewProduct.order)
        .options(joinedload(Product.price_tiers).joinedload(PriceTier.prices))
    )

    for product in products:
        pts = [tier for tier in product.price_tiers if tier.active]
        if len(pts) > 1:
            app.logger.error(
                "Multiple active PriceTiers found for %s. Excluding product.", product
            )
            continue

        pt = pts[0]

        tiers[pt.id] = pt

    basket = Basket.from_session(current_user, get_user_currency())

    form = TicketAmountsForm()

    """
    For consistency and to avoid surprises, we try to ensure a few things here:
    - if the user successfully submits a form with no errors, their basket is updated
    - if they don't, the basket is left untouched
    - the basket is updated to match what was submitted, even if they added tickets in another tab
    - if they already have tickets in their basket, only reserve the extra tickets as necessary
    - don't unreserve surplus tickets until the payment is created
    - if the user hasn't submitted anything, we use their current reserved ticket counts
    - if the user has reserved tickets from exhausted tiers on this view, we still show them
    - if the user has reserved tickets from other views, don't show and don't mess with them
    - this means the user can combine tickets from multiple views into a single basket
    - show the sold-out/unavailable states only when the user doesn't have reserved tickets

    We currently don't deal with multiple price tiers being available around the same time.
    Reserved tickets from a previous tier should be cancelled before activating a new one.
    """
    if request.method != "POST":
        # Empty form - populate products
        for pt_id, tier in tiers.items():
            form.tiers.append_entry()
            f = form.tiers[-1]
            f.tier_id.data = pt_id

            f.amount.data = basket.get(tier, 0)

    # Whether submitted or not, update the allowed amounts before validating
    capacity_gone = False
    for f in form.tiers:
        pt_id = f.tier_id.data
        tier = tiers[pt_id]
        f._tier = tier

        # If they've already got reserved tickets, let them keep them
        user_limit = max(tier.user_limit(), basket.get(tier, 0))
        if f.amount.data and f.amount.data > user_limit:
            capacity_gone = True
        values = range(user_limit + 1)
        f.amount.values = values
        f._any = any(values)

    available = True
    if sales_state == "unavailable":
        if not any(p.product in products for p in basket.purchases):
            # If they have any reservations, they bypass the unavailable state.
            # This means someone can use another view to get access to this one
            # again. I'm not sure what to do about this. It usually won't matter.
            available = False

    if form.validate_on_submit() and (
        form.buy_tickets.data or form.buy_hire.data or form.buy_other.data
    ):
        # User has selected some tickets to buy.
        return handle_ticket_selection(form, view, flow, available, basket)

    if request.method == "POST" and form.set_currency.data:
        if form.set_currency.validate(form):
            app.logger.info("Updating currency to %s only", form.set_currency.data)
            set_user_currency(form.set_currency.data)
            db.session.commit()

            for field in form:
                field.errors = []

    if capacity_gone:
        no_capacity.inc()
        flash(
            "We're sorry, but there is not enough capacity available to "
            "allocate these tickets. You may be able to try again with a smaller amount."
        )

    form.currency_code.data = get_user_currency()
    return render_template(
        "tickets/choose.html", form=form, flow=flow, view=view, available=available
    )


def handle_ticket_selection(form, view, flow, available, basket):
    if form.currency_code.data != get_user_currency():
        set_user_currency(form.currency_code.data)
        # Commit so we don't lose the currency change if an error occurs
        db.session.commit()
        # Reload the basket because set_user_currency has changed it under us
        basket = Basket.from_session(current_user, get_user_currency())

    for f in form.tiers:
        pt = f._tier
        if f.amount.data != basket.get(pt, 0):
            app.logger.info("Adding %s %s tickets to basket", f.amount.data, pt.name)
            basket[pt] = f.amount.data

    if not available:
        app.logger.warn("User has no reservations, enforcing unavailable state")
        basket.save_to_session()
        return redirect(url_for("tickets.main", flow=flow))

    if not any(basket.values()):
        empty_baskets.inc()
        if view.type == "tickets":
            flash("Please select at least one ticket to buy.")
        elif view.type == "hire":
            flash("Please select at least one item to hire.")
        else:
            flash("Please select at least one item to buy.")

        basket.save_to_session()
        return redirect(url_for("tickets.main", flow=flow))

    app.logger.info("Basket %s", basket)

    try:
        basket.create_purchases()
        basket.ensure_purchase_capacity()

        db.session.commit()

    except CapacityException as e:
        # Damn, capacity's gone since we created the purchases
        # Redirect back to show what's currently in the basket
        db.session.rollback()
        no_capacity.inc()
        app.logger.warn("Limit exceeded creating tickets: %s", e)
        flash(
            "We're very sorry, but there is not enough capacity available to "
            "allocate these tickets. You may be able to try again with a smaller amount."
        )
        return redirect(url_for("tickets.main", flow=flow))

    basket.save_to_session()

    if basket.total != 0:
        # Send the user off to pay
        return redirect(url_for("tickets.pay", flow=flow))
    else:
        return handle_free_tickets(form, flow, view, basket)


def handle_free_tickets(form, flow, view, basket):
    # The user is trying to "buy" free tickets.
    # They must be authenticated for this.
    if not current_user.is_authenticated:
        app.logger.warn("User is not authenticated, sending to login")
        flash("You must be logged in to buy additional free tickets")
        return redirect(url_for("users.login", next=url_for("tickets.main", flow=flow)))

    # We sell under-12 tickets to non-CfP users, to enforce capacity.
    # We don't let people order an under-12 ticket on its own.
    # However, CfP users need to be able to buy day and parking tickets.
    admissions_tickets = current_user.get_owned_tickets(type="admission_ticket")
    if not any(admissions_tickets) and not view.cfp_accepted_only:
        app.logger.warn("User trying to buy free add-ons without an admission ticket")
        flash("You must have an admissions ticket to buy additional free tickets")
        return redirect(url_for("tickets.main", flow=flow))

    basket.user = current_user
    basket.check_out_free()
    db.session.commit()

    Basket.clear_from_session()

    msg = Message(
        "Your EMF ticket order",
        sender=app.config["TICKETS_EMAIL"],
        recipients=[current_user.email],
    )

    already_emailed = set_tickets_emailed(current_user)
    msg.body = render_template(
        "emails/tickets-ordered-email-free.txt",
        user=current_user,
        basket=basket,
        already_emailed=already_emailed,
    )
    if feature_enabled("ISSUE_TICKETS"):
        attach_tickets(msg, current_user)

    mail.send(msg)

    if len(basket.purchases) == 1:
        flash("Your ticket has been confirmed")
    else:
        flash("Your tickets have been confirmed")

    return redirect(url_for("users.purchases"))


@tickets.route("/tickets/clear")
@tickets.route("/tickets/<flow>/clear")
def tickets_clear(flow=None):
    basket = Basket.from_session(current_user, get_user_currency())
    basket.cancel_purchases()
    db.session.commit()

    Basket.clear_from_session()
    return redirect(url_for("tickets.main", flow=flow))


@tickets.route("/tickets/voucher/")
@tickets.route("/tickets/voucher/<voucher_code>")
def tickets_voucher(voucher_code=None):
    """
        A user reaches this endpoint if they're sent a voucher code by email.
        Set up the voucher details in the session and redirect them to choose their tickets.
    """
    voucher = Voucher.get_by_code(voucher_code)
    if voucher is None:
        return abort(404)

    if voucher.is_used:
        if current_user.is_authenticated:
            flash(
                """The voucher you have supplied has been used.
                   If it was you who used it, the status of your purchase is below.
                   Cancelling the payment made with the voucher will reactivate it so you can try again.
                """
            )
            return redirect(url_for("users.purchases"))
        else:
            abort(404)

    view = voucher.view
    if view:
        session["ticket_voucher"] = voucher_code
        return redirect(url_for("tickets.main", flow=view.name))

    if "ticket_voucher" in session:
        del session["ticket_voucher"]

    invalid_vouchers.inc()
    flash("Ticket voucher was invalid")
    return redirect(url_for("tickets.main"))
