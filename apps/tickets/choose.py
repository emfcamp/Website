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
from . import tickets, empty_baskets, no_capacity, invalid_vouchers, get_product_view


@tickets.route("/tickets", methods=["GET", "POST"])
@tickets.route("/tickets/<flow>", methods=["GET", "POST"])
def main(flow="main"):
    """The main tickets page. This lets the user choose which tickets to buy,
    creates a basket for them and then adds the tickets to their basket.

    At this point tickets are reserved, and the user is passed on to `/tickets/pay`
    to enter their user details and choose a payment method.

    The `flow` parameter dictates which ProductView to display on this page,
    allowing us to have different categories of items on sale, for example tickets
    on one page, and t-shirts on a separate page.
    """
    # Fetch the ProductView and determine if this user is allowed to view it.
    view = get_product_view(flow)

    if view.cfp_accepted_only and current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".main", flow=flow)))

    if not view.is_accessible(current_user, session.get("ticket_voucher")):
        # User isn't allowed to see this ProductView, either because it's
        # CfP-restricted or because they don't have an active voucher.
        abort(404)

    # The sales state controls whether admission tickets are on sale.
    sales_state = get_sales_state()

    if sales_state in {"unavailable", "sold-out"}:
        # For the main entry point, we assume people want admissions tickets,
        # but we still need to sell people parking tickets, tents or tickets
        # from vouchers until the final cutoff (sales-ended).
        if flow != "main":
            sales_state = "available"

    if app.config.get("DEBUG"):
        sales_state = request.args.get("sales_state", sales_state)

    if sales_state in {"available", "unavailable"}:
        # Tickets are on sale, or they're unavailable but we're still showing prices.
        pass
    elif not current_user.is_anonymous and current_user.has_permission("admin"):
        # Admins always have access
        pass
    else:
        # User is prevented from buying by the sales state.
        return render_template("tickets/cutoff.html")

    # OK, looks like we can try and sell the user some stuff.
    products = products_for_view(view)
    form = TicketAmountsForm(products)
    basket = Basket.from_session(current_user, get_user_currency())

    if request.method != "POST":
        # Empty form - populate products with any amounts already in basket
        form.populate(basket)

    # Validate the capacity in the form, setting the maximum limits where available.
    if not form.ensure_capacity(basket):
        # We're not able to provide the number of tickets the user has selected.
        no_capacity.inc()
        flash(
            "We're sorry, but there weren't enough tickets remaining to give "
            "you all the tickets you requested. We've reserved as many as we can for you."
        )

    available = True
    if sales_state == "unavailable":
        # If the user has any reservations, they bypass the unavailable state.
        # This means someone can use another view to get access to this one
        # again. I'm not sure what to do about this. It usually won't matter.
        available = any(p.product in products for p in basket.purchases)

    if form.validate_on_submit() and (
        form.buy_tickets.data or form.buy_hire.data or form.buy_other.data
    ):
        # User has selected some tickets to buy.
        if not available:
            # Tickets are out :(
            app.logger.warn("User has no reservations, enforcing unavailable state")
            basket.save_to_session()
            return redirect(url_for("tickets.main", flow=flow))

        return handle_ticket_selection(form, view, flow, basket)

    if request.method == "POST" and form.set_currency.data:
        # User has changed their currency but they don't have javascript enabled,
        # so a page reload has been caused.
        if form.set_currency.validate(form):
            app.logger.info(
                "Updating currency to %s (no-JS path)", form.set_currency.data
            )
            set_user_currency(form.set_currency.data)
            db.session.commit()

            for field in form:
                field.errors = []

    form.currency_code.data = get_user_currency()
    return render_template(
        "tickets/choose.html", form=form, flow=flow, view=view, available=available
    )


def products_for_view(product_view) -> list[ProductViewProduct]:
    # Note that this function is performance-critical. It should load all the product data
    # necessary for the high-traffic tickets page to render in a single query. If you change
    # this, make sure that you monitor the number of queries emitted by the tickets page.
    return (
        ProductViewProduct.query.filter_by(view_id=product_view.id)
        .join(ProductViewProduct.product)
        .with_entities(Product)
        .order_by(ProductViewProduct.order)
        .options(joinedload(Product.price_tiers).joinedload(PriceTier.prices))
        .options(joinedload(Product.parent))
        .options(joinedload("parent.parent"))
    ).all()


def handle_ticket_selection(form, view: ProductView, flow: str, basket: Basket):
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
    if form.currency_code.data != get_user_currency():
        set_user_currency(form.currency_code.data)
        # Commit so we don't lose the currency change if an error occurs
        db.session.commit()
        # Reload the basket because set_user_currency has changed it under us
        basket = Basket.from_session(current_user, get_user_currency())

    form.add_to_basket(basket)

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

    # Ensure this purchase is valid for this voucher.
    voucher = Voucher.get_by_code(basket.voucher)
    if voucher and not voucher.check_capacity(basket):
        basket.save_to_session()
        if voucher.is_used:
            flash("Your voucher has been used by someone else.")
        else:
            flash(
                f"You can only purchase {voucher.tickets_remaining} adult "
                "tickets with this voucher. Please select fewer tickets."
            )
        return redirect(url_for("tickets.main", flow=flow))

    app.logger.info("Saving basket %s", basket)

    try:
        # Convert the user's basket into a purchase.
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
        return handle_free_tickets(flow, view, basket)


def handle_free_tickets(flow: str, view: ProductView, basket: Basket):
    """The user is trying to "buy" only free tickets.

    This is effectively a payment stage, handled differently
    from the rest of the flow.
    """
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
def tickets_clear(flow: str = None):
    app.logger.info("Clearing basket")
    basket = Basket.from_session(current_user, get_user_currency())
    basket.cancel_purchases()
    db.session.commit()

    Basket.clear_from_session()
    return redirect(url_for("tickets.main", flow=flow))


@tickets.route("/tickets/voucher/")
@tickets.route("/tickets/voucher/<voucher_code>")
def tickets_voucher(voucher_code: str = None):
    """
    A user reaches this endpoint if they're sent a voucher code by email.
    Set up the voucher details in the session and redirect them to choose their tickets.
    """
    if voucher_code is None:
        return abort(404)

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
