from . import admin

from flask import (
    render_template,
    redirect,
    flash,
    url_for,
    current_app as app,
    abort,
    send_file,
)
from flask_mail import Message

from main import db, mail, external_url
from models.exc import CapacityException
from models.user import User
from models.product import ProductGroup, Product, PriceTier, Price
from models.purchase import Purchase, Ticket, PurchaseTransfer

from .forms import (
    IssueTicketsInitialForm,
    IssueTicketsForm,
    IssueFreeTicketsNewUserForm,
    ReserveTicketsForm,
    ReserveTicketsNewUserForm,
    CancelTicketForm,
    ConvertTicketForm,
    TransferTicketInitialForm,
    TransferTicketForm,
    TransferTicketNewUserForm,
)

from ..common import feature_enabled
from ..common.receipt import attach_tickets, set_tickets_emailed
from ..common.receipt import render_receipt, render_pdf


@admin.route("/tickets")
@admin.route("/tickets/paid")
def tickets():
    tickets = Ticket.query.filter_by(is_paid_for=True).order_by(Ticket.id).all()

    return render_template("admin/tickets/tickets.html", tickets=tickets)


@admin.route("/tickets/unpaid")
def tickets_unpaid():
    tickets = (
        Purchase.query.filter_by(is_paid_for=False)
        .filter(~Purchase.owner_id.is_(None))
        .order_by(Purchase.id)
        .all()
    )

    return render_template("admin/tickets/tickets.html", tickets=tickets)


@admin.route("/tickets/issue", methods=["GET", "POST"])
def tickets_issue():
    form = IssueTicketsInitialForm()
    if form.validate_on_submit():
        if form.issue_free.data:
            return redirect(url_for(".tickets_issue_free", email=form.email.data))
        elif form.reserve.data:
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
            app.logger.info(
                "Creating new user with email %s and name %s", email, form.name.data
            )
            user = User(email, form.name.data)
            db.session.add(user)
            flash("Created account for %s" % email)

        basket = form.create_basket(user)
        app.logger.info("Admin basket for %s %s", user.email, basket)

        try:
            basket.create_purchases()
            basket.ensure_purchase_capacity()
            assert basket.total == 0

        except CapacityException as e:
            db.session.rollback()
            app.logger.warn("Limit exceeded creating admin tickets: %s", e)
            return redirect(url_for(".tickets_issue_free", email=email))

        for p in basket.purchases:
            p.set_state("paid")

        app.logger.info("Allocated %s tickets to user", len(basket.purchases))
        db.session.commit()

        code = user.login_code(app.config["SECRET_KEY"])
        msg = Message(
            "Your complimentary tickets to Electromagnetic Field",
            sender=app.config["TICKETS_EMAIL"],
            recipients=[user.email],
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

        mail.send(msg)
        db.session.commit()

        flash("Allocated %s ticket(s)" % len(basket.purchases))
        return redirect(url_for(".tickets_issue"))
    return render_template(
        "admin/tickets/tickets-issue-free.html", form=form, user=user, email=email
    )


@admin.route("/tickets/list-free")
def list_free_tickets():
    # Complimentary tickets and transferred tickets can both have no payment.
    # This page is actually intended to be a list of complimentary tickets.
    free_tickets = (
        Purchase.query.join(PriceTier, Product)
        .filter(
            Purchase.is_paid_for,
            Purchase.payment_id.is_(None),
            ~PurchaseTransfer.query.filter(
                PurchaseTransfer.purchase.expression
            ).exists(),
        )
        .order_by(Purchase.owner_id, Purchase.id)
        .all()
    )

    return render_template(
        "admin/tickets/tickets-list-free.html", free_tickets=free_tickets
    )


@admin.route("/ticket/<int:ticket_id>/cancel-free", methods=["GET", "POST"])
def cancel_free_ticket(ticket_id):
    ticket = Purchase.query.get_or_404(ticket_id)
    if ticket.payment is not None:
        abort(404)

    form = CancelTicketForm()
    if form.validate_on_submit():
        if form.cancel.data:
            app.logger.info("Cancelling free ticket %s", ticket.id)
            ticket.cancel()

            db.session.commit()

            flash("Ticket cancelled")
            return redirect(url_for("admin.list_free_tickets"))

    return render_template(
        "admin/tickets/ticket-cancel-free.html", ticket=ticket, form=form
    )


@admin.route("/ticket/<int:ticket_id>/convert")
@admin.route(
    "/ticket/<int:ticket_id>/convert/<int:price_tier_id>", methods=["GET", "POST"]
)
def convert_ticket(ticket_id, price_tier_id=None):
    ticket = Purchase.query.get_or_404(ticket_id)

    new_tier = None
    if price_tier_id is not None:
        new_tier = PriceTier.query.get(price_tier_id)

    form = ConvertTicketForm()
    if form.validate_on_submit():
        if form.convert.data:
            app.logger.info(
                "Converting ticket %s to %s (tier %s, product %s)",
                ticket.id,
                new_tier.id,
                new_tier.parent.name,
            )

            assert ticket.price_tier != new_tier

            with db.session.no_autoflush:
                ticket.price_tier.return_instances(1)
                new_tier.issue_instances(1)

            db.session.flush()
            if new_tier.get_total_remaining_capacity() < 0:
                db.session.rollback()
                flash("Insufficient capacity to convert ticket")
                return redirect(
                    url_for(
                        ".convert_ticket",
                        ticket_id=ticket.id,
                        price_tier_id=price_tier_id,
                    )
                )

            ticket.price = new_tier.get_price(ticket.price.currency)
            ticket.price_tier = new_tier
            ticket.product = new_tier.parent

            db.session.commit()
            flash("Ticket converted")
            return redirect(url_for(".convert_ticket", ticket_id=ticket.id))

    convertible_tiers = (
        Price.query.filter_by(
            currency=ticket.price.currency, price_int=ticket.price.price_int
        )
        .join(PriceTier)
        .with_entities(PriceTier)
        .order_by(PriceTier.id)
    )

    return render_template(
        "admin/tickets/ticket-convert.html",
        ticket=ticket,
        form=form,
        convertible_tiers=convertible_tiers,
        new_tier=new_tier,
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
        PriceTier.query.join(Product, ProductGroup)
        .order_by(ProductGroup.name, Product.display_name, Product.id)
        .all()
    )

    form.add_price_tiers(pts)

    if form.validate_on_submit():
        if not user:
            name = form.name.data

            app.logger.info("Creating new user with email %s and name %s", email, name)
            user = User(email, name)
            flash("Created account for %s" % name)
            db.session.add(user)

        basket = form.create_basket(user)

        app.logger.info("Admin basket for %s %s", user.email, basket)

        try:
            basket.create_purchases()
            basket.ensure_purchase_capacity()

            db.session.commit()

        except CapacityException as e:
            db.session.rollback()
            app.logger.warn("Limit exceeded creating admin tickets: %s", e)
            return redirect(url_for(".tickets_reserve", email=email))

        code = user.login_code(app.config["SECRET_KEY"])
        msg = Message(
            "Your reserved tickets to EMF",
            sender=app.config["TICKETS_EMAIL"],
            recipients=[user.email],
        )

        msg.body = render_template(
            "emails/tickets-reserved.txt",
            user=user,
            code=code,
            tickets=basket.purchases,
            new_user=new_user,
            currency=form.currency.data,
        )

        mail.send(msg)
        db.session.commit()

        flash("Reserved tickets and emailed {}".format(user.email))
        return redirect(url_for(".tickets_issue"))

    return render_template(
        "admin/tickets/tickets-reserve.html", form=form, pts=pts, user=user
    )


@admin.route("/tickets/<int:ticket_id>/transfer", methods=["GET", "POST"])
def transfer_ticket(ticket_id):
    form = TransferTicketInitialForm()
    if form.validate_on_submit():
        return redirect(
            url_for(".transfer_ticket_user", ticket_id=ticket_id, email=form.email.data)
        )
    return render_template("admin/tickets/transfer-ticket.html", form=form)


@admin.route("/tickets/<int:ticket_id>/transfer/<email>", methods=["GET", "POST"])
def transfer_ticket_user(ticket_id, email):
    ticket = Ticket.query.get_or_404(ticket_id)

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
            flash("Created account for %s" % name)
            db.session.add(user)

        ticket = Ticket.query.with_for_update().get(ticket.id)

        previous_owner = ticket.owner
        # This contract is loopy
        ticket.transfer(from_user=previous_owner, to_user=user)
        db.session.commit()

        app.logger.info(
            "Ticket %s transferred from %s to %s", ticket, previous_owner, user
        )

        # We don't send any emails because this is an admin operation

        flash("Transferred ticket {}".format(ticket.id))
        return redirect(url_for(".user", user_id=user.id))

    return render_template(
        "admin/tickets/transfer-ticket-user.html", form=form, ticket=ticket, user=user
    )


@admin.route("/user/<int:user_id>/tickets")
@admin.route("/user/<int:user_id>/tickets<ext>")
def user_tickets(user_id, ext=None):
    user = User.query.get_or_404(user_id)

    receipt = render_receipt(user)

    if ext == ".pdf":
        url = external_url(".user_tickets", user_id=user_id)
        return send_file(
            render_pdf(url, receipt), mimetype="application/pdf", cache_timeout=60
        )

    return receipt
