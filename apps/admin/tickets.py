from flask import (
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
from flask.typing import ResponseReturnValue
from flask_mailman import EmailMessage

from main import db, external_url, get_or_404
from models.exc import CapacityException
from models.product import Price, PriceTier, Product, ProductGroup
from models.purchase import Purchase, PurchaseTransfer, Ticket
from models.user import User

from ..common import feature_enabled
from ..common.receipt import attach_tickets, render_pdf, render_receipt, set_tickets_emailed
from ..config import config
from ..payments.refund import create_stripe_refund
from . import admin
from .forms import (
    CancelTicketForm,
    ConvertTicketForm,
    IssueFreeTicketsNewUserForm,
    IssueTicketsForm,
    IssueTicketsInitialForm,
    ReserveTicketsForm,
    ReserveTicketsNewUserForm,
    TransferTicketForm,
    TransferTicketInitialForm,
    TransferTicketNewUserForm,
)


@admin.route("/tickets")
@admin.route("/tickets/paid")
def tickets():
    tickets = Ticket.query.filter_by(is_paid_for=True).order_by(Ticket.id).all()

    return render_template("admin/tickets/tickets.html", tickets=tickets)


@admin.route("/tickets/unpaid")
def tickets_unpaid():
    query = (
        Purchase.query.filter_by(is_paid_for=False)
        .filter(~Purchase.owner_id.is_(None))
        .filter(Purchase.state.in_(["reserved", "admin-reserved", "payment-pending"]))
        .order_by(Purchase.id)
    )

    return render_template("admin/tickets/tickets.html", tickets=query.all())


@admin.route("/tickets/issue", methods=["GET", "POST"])
def tickets_issue():
    form = IssueTicketsInitialForm()
    if form.validate_on_submit():
        if form.issue_free.data:
            return redirect(url_for(".tickets_issue_free", email=form.email.data))
        if form.reserve.data:
            return redirect(url_for(".tickets_reserve", email=form.email.data))
    return render_template("admin/tickets/tickets-issue.html", form=form)


@admin.route("/tickets/issue-free/<email>", methods=["GET", "POST"])
def tickets_issue_free(email):
    user = User.get_by_email(email)

    if user is None:
        form = IssueFreeTicketsNewUserForm()
        new_user = True
    else:
        form = IssueTicketsForm()
        new_user = False

    free_pts = (
        PriceTier.query.join(Product)
        .filter(~PriceTier.prices.any(Price.price_int > 0))
        .order_by(Product.name)
        .all()
    )

    form.add_price_tiers(free_pts)

    if form.validate_on_submit():
        if not user:
            app.logger.info("Creating new user with email %s and name %s", email, form.name.data)
            user = User(email, form.name.data)
            db.session.add(user)
            flash(f"Created account for {email}")

        basket = form.create_basket(user)
        app.logger.info("Admin basket for %s %s", user.email, basket)

        try:
            basket.create_purchases()
            basket.ensure_purchase_capacity()
            assert basket.total == 0

        except CapacityException as e:
            db.session.rollback()
            app.logger.warning("Limit exceeded creating admin tickets: %s", e)
            return redirect(url_for(".tickets_issue_free", email=email))

        for p in basket.purchases:
            p.set_state("paid")

        app.logger.info("Allocated %s tickets to user", len(basket.purchases))
        db.session.commit()

        code = user.login_code(app.config["SECRET_KEY"])
        ticket_noun = "tickets" if len(basket.purchases) > 1 else "ticket"
        msg = EmailMessage(
            f"Your complimentary {ticket_noun} to Electromagnetic Field",
            from_email=config.from_email("TICKETS_EMAIL"),
            to=[user.email],
        )

        already_emailed = set_tickets_emailed(user)
        msg.body = render_template(
            "emails/tickets-free.txt",
            user=user,
            code=code,
            tickets=basket.purchases,
            new_user=new_user,
            already_emailed=already_emailed,
        )

        if feature_enabled("ISSUE_TICKETS"):
            attach_tickets(msg, user)

        msg.send()
        db.session.commit()

        flash(f"Allocated {len(basket.purchases)} {ticket_noun}")
        return redirect(url_for(".tickets_issue"))
    return render_template("admin/tickets/tickets-issue-free.html", form=form, user=user, email=email)


@admin.route("/tickets/list-free")
def list_free_tickets():
    # Complimentary tickets and transferred tickets can both have no payment.
    # This page is actually intended to be a list of complimentary tickets.
    free_tickets = (
        Purchase.query.join(PriceTier)
        .join(Product)
        .filter(
            Purchase.is_paid_for,
            Purchase.payment_id.is_(None),
            ~PurchaseTransfer.query.filter(PurchaseTransfer.purchase.expression).exists(),
        )
        .order_by(Purchase.owner_id, Purchase.id)
        .all()
    )

    return render_template("admin/tickets/tickets-list-free.html", free_tickets=free_tickets)


@admin.route("/ticket/<int:ticket_id>", methods=["GET"])
def view_ticket(ticket_id: int) -> ResponseReturnValue:
    ticket = get_or_404(db, Ticket, ticket_id)
    return render_template(
        "admin/tickets/view_ticket.html",
        ticket=ticket,
    )


@admin.route("/ticket/<int:ticket_id>/cancel-free", methods=["GET", "POST"])
def cancel_free_ticket(ticket_id: int) -> ResponseReturnValue:
    ticket = get_or_404(db, Purchase, ticket_id)

    if not ticket.is_free:
        abort(400)

    form = CancelTicketForm()
    if form.validate_on_submit():
        if form.cancel.data:
            app.logger.info("Cancelling free ticket %s", ticket.id)
            ticket.cancel()

            db.session.commit()

            flash("Ticket cancelled")
            return redirect(url_for("admin.list_free_tickets"))

    return render_template("admin/tickets/ticket-cancel-free.html", ticket=ticket, form=form)


@admin.route("/ticket/<int:ticket_id>/convert")
@admin.route("/ticket/<int:ticket_id>/convert/<int:price_tier_id>", methods=["GET", "POST"])
def convert_ticket(ticket_id, price_tier_id=None):
    allow_refund = request.args.get("allow_refund", None) == "True"

    ticket = get_or_404(db, Purchase, ticket_id)

    def flash_and_bail(*args, bad_tier=True, **kwargs):
        flash(*args, **kwargs)
        url_args = {
            "ticket_id": ticket.id,
            "allow_refund": str(allow_refund),
        }
        if not bad_tier:
            url_args["price_tier_id"] = price_tier_id
        return redirect(
            url_for(
                ".convert_ticket",
                **url_args,
            )
        )

    new_tier = None
    new_price = None
    price_change = None
    if price_tier_id is not None:
        new_tier = PriceTier.query.get(price_tier_id)

        new_price = new_tier.get_price(ticket.price.currency)
        if new_price:
            price_change = ticket.price.value - new_price.value

        if allow_refund:
            if not new_price:
                # The new tier must have a price in the same currency.
                return flash_and_bail(
                    "New price tier has no price in the same currency as the ticket was sold in", "danger"
                )
            if new_price.price_int > ticket.price.price_int:
                return flash_and_bail(
                    "New price tier cannot be worth more than the previous price tier", "danger"
                )
        elif price_change:
            return flash_and_bail(
                f"New price tier costs {new_price} which is not the same as ticket price {ticket.price}, and issuing a partial refund has not been explicitly enabled",
                "danger",
            )

        if price_change:
            payment = ticket.payment
            if payment.provider != "stripe":
                return flash_and_bail(
                    "Ticket conversions involving non-Stripe refunds must be done manually", "danger"
                )
            if not payment.is_refundable(ignore_event_refund_state=True):
                return flash_and_bail("The payment is not in a state where refunds are possible", "danger")

        if ticket.price_tier == new_tier:
            return flash_and_bail("Cannot convert ticket to its current price tier", "danger")

    form = ConvertTicketForm()
    if form.validate_on_submit():
        if form.convert.data:
            app.logger.info(
                "Converting ticket %s to %s (tier %s, product %s) (old price %s, new price %s, changing? %s)",
                ticket.id,
                new_tier.id,
                new_tier.parent.name,
                ticket.price,
                new_price,
                price_change,
            )

            with db.session.no_autoflush:
                ticket.price_tier.return_instances(1)
                new_tier.issue_instances(1)

            db.session.flush()
            if new_tier.get_total_remaining_capacity() < 0:
                db.session.rollback()
                return flash_and_bail("Insufficient capacity to convert ticket", "danger", bad_tier=False)

            if price_change:
                # We're doing the part-refund for real.
                refund_amount = ticket.price.value - new_price.value
                assert refund_amount > 0, "Refund amount is non-zero; we should have caught this already!"
                app.logger.info(
                    "Creating Stripe admin-conversion part-refund for %s of %s",
                    ticket,
                    refund_amount,
                )
                refund = create_stripe_refund(
                    ticket.payment,
                    refund_amount,
                    {
                        "type": "admin-conversion",
                        "purchase_id": ticket.id,
                        "old_price_tier": ticket.price_tier.id,
                        "old_price": ticket.price.id,
                        "old_product": ticket.product,
                        "new_price_tier": new_tier.id,
                        "new_price": new_price.id,
                        "new_product": new_tier.parent,
                    },
                )
                db.session.add(refund)
                flash("Created part refund", "success")

            ticket.price = new_price
            ticket.price_tier = new_tier
            ticket.product = new_tier.parent

            db.session.commit()
            flash("Ticket converted", "success")
            return redirect(url_for(".convert_ticket", ticket_id=ticket.id))

    price_query = db.session.query(Price).filter_by(currency=ticket.price.currency)
    if allow_refund:
        price_query = price_query.filter(Price.price_int <= ticket.price.price_int)
    else:
        price_query = price_query.filter(Price.price_int == ticket.price.price_int)

    convertible_tiers = price_query.join(PriceTier).with_entities(PriceTier).order_by(PriceTier.id)

    return render_template(
        "admin/tickets/ticket-convert.html",
        ticket=ticket,
        form=form,
        convertible_tiers=convertible_tiers,
        new_tier=new_tier,
        price_change=price_change,
        allow_refund=allow_refund,
    )


@admin.route("/tickets/reserve/<email>", methods=["GET", "POST"])
def tickets_reserve(email):
    user = User.get_by_email(email)

    if user is None:
        form = ReserveTicketsNewUserForm()
        new_user = True
    else:
        form = ReserveTicketsForm()
        new_user = False

    pts = (
        PriceTier.query.join(Product)
        .join(ProductGroup)
        .order_by(ProductGroup.name, Product.display_name, Product.id)
        .all()
    )

    form.add_price_tiers(pts)

    if form.validate_on_submit():
        if not user:
            name = form.name.data

            app.logger.info("Creating new user with email %s and name %s", email, name)
            user = User(email, name)
            flash(f"Created account for {name}")
            db.session.add(user)

        basket = form.create_basket(user)

        app.logger.info("Admin basket for %s %s", user.email, basket)

        try:
            basket.create_purchases()
            basket.ensure_purchase_capacity()

            for p in basket.purchases:
                p.state = "admin-reserved"

            db.session.commit()

        except CapacityException as e:
            db.session.rollback()
            app.logger.warning("Limit exceeded creating admin tickets: %s", e)
            return redirect(url_for(".tickets_reserve", email=email))

        code = user.login_code(app.config["SECRET_KEY"])
        ticket_noun = "tickets" if len(basket.purchases) > 1 else "ticket"
        msg = EmailMessage(
            f"Your reserved {ticket_noun} to EMF",
            from_email=config.from_email("TICKETS_EMAIL"),
            to=[user.email],
        )

        msg.body = render_template(
            "emails/admin-tickets-reserved.txt",
            user=user,
            code=code,
            tickets=basket.purchases,
            new_user=new_user,
            currency=form.currency.data,
        )

        msg.send()
        db.session.commit()

        flash(f"Reserved {ticket_noun} and emailed {user.email}")
        return redirect(url_for(".tickets_issue"))

    return render_template("admin/tickets/tickets-reserve.html", form=form, pts=pts, user=user)


@admin.route("/tickets/<int:ticket_id>/transfer", methods=["GET", "POST"])
def transfer_ticket(ticket_id):
    form = TransferTicketInitialForm()
    if form.validate_on_submit():
        return redirect(url_for(".transfer_ticket_user", ticket_id=ticket_id, email=form.email.data))
    return render_template("admin/tickets/transfer-ticket.html", form=form)


@admin.route("/tickets/<int:ticket_id>/transfer/<email>", methods=["GET", "POST"])
def transfer_ticket_user(ticket_id, email):
    ticket = get_or_404(db, Ticket, ticket_id)

    if not ticket.is_paid_for:
        flash("Unpaid tickets cannot be transferred")
        return redirect(url_for(".user", user_id=ticket.owner_id))

    if not ticket.product.get_attribute("is_transferable"):
        flash("This purchase cannot be transferred")
        return redirect(url_for(".user", user_id=ticket.owner_id))

    user = User.get_by_email(email)

    if user is None:
        form = TransferTicketNewUserForm()
    else:
        form = TransferTicketForm()

    if form.validate_on_submit():
        if not user:
            name = form.name.data

            app.logger.info("Creating new user with email %s and name %s", email, name)
            user = User(email, name)
            flash(f"Created account for {name}")
            db.session.add(user)

        ticket = Ticket.query.with_for_update().get(ticket.id)

        previous_owner = ticket.owner
        # This contract is loopy
        ticket.transfer(from_user=previous_owner, to_user=user)
        db.session.commit()

        app.logger.info("Ticket %s transferred from %s to %s", ticket, previous_owner, user)

        # We don't send any emails because this is an admin operation

        flash(f"Transferred ticket {ticket.id}")
        return redirect(url_for(".user", user_id=user.id))

    return render_template("admin/tickets/transfer-ticket-user.html", form=form, ticket=ticket, user=user)


@admin.route("/user/<int:user_id>/tickets")
@admin.route("/user/<int:user_id>/tickets<ext>")
def user_tickets(user_id, ext=None):
    user = get_or_404(db, User, user_id)

    receipt = render_receipt(user)

    if ext == ".pdf":
        url = external_url(".user_tickets", user_id=user_id)
        return send_file(render_pdf(url, receipt), mimetype="application/pdf", max_age=60)

    return receipt
