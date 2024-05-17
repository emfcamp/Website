from datetime import datetime, timedelta

from flask import current_app as app, render_template
from flask_mailman import EmailMessage
from sqlalchemy import func

from main import db
from apps.common import feature_enabled
from ..common.email import from_email
from apps.common.receipt import attach_tickets, set_tickets_emailed, RECEIPT_TYPES
from models.payment import Payment
from models.product import (
    ProductGroup,
    Product,
    PriceTier,
    Price,
    ProductView,
    ProductViewProduct,
)
from models.scheduled_task import scheduled_task
from models.purchase import Purchase
from models.user import User

from . import tickets


def create_product_groups():
    top_level_groups = [
        # name, capacity, expires, redeemable
        ("admissions", None, 2500, True),
        ("parking", None, None, False),
        ("campervan", None, None, False),
        ("merchandise", None, None, True),
    ]
    for name, expires, capacity, redeemable in top_level_groups:
        if ProductGroup.get_by_name(name):
            continue
        pg = ProductGroup(name=name, type=name, capacity_max=capacity, expires=expires, attributes={"is_redeemable": redeemable})
        db.session.add(pg)

    db.session.flush()

    allocations = [
        # name, capacity
        ("vendors", 100),
        ("sponsors", 200),
        ("speakers", 100),
        ("general", 1800),
    ]

    admissions = ProductGroup.get_by_name("admissions")
    for name, capacity in allocations:
        if ProductGroup.get_by_name(name):
            continue
        ProductGroup(name=name, capacity_max=capacity, parent=admissions)

    view = ProductView.get_by_name("main")
    if not view:
        view = ProductView(name="main", type="tickets")
        db.session.add(view)

    db.session.flush()

    general = ProductGroup.get_by_name("general")

    products = [
        # name, display name, transferable, capacity, description, vat_rate, (std cap, gbp eur), (early cap, gbp, eur), (late cap, gbp, eur)
        (
            "full",
            "Full Camp Ticket",
            True,
            None,
            "Full ticket",
            0.2,
            ((1500, 115, 135), (250, 105, 125), (None, 125, 145)),
        ),
        (
            "full-s",
            "Full Camp Ticket (Supporter)",
            True,
            None,
            "Support this non-profit event by paying a bit more. All money will go towards making EMF more awesome.",
            0.2,
            ((None, 150, 180),),
        ),
        (
            "full-sg",
            "Full Camp Ticket (Gold Supporter)",
            True,
            None,
            "Support this non-profit event by paying a bit more. All money will go towards making EMF more awesome.",
            0.2,
            ((None, 200, 240),),
        ),
        (
            "u18",
            "Under-18",
            True,
            150,
            "For visitors born after August 30th, 2000. All under-18s must be accompanied by an adult.",
            0.2,
            ((None, 55, 63),),
        ),
        (
            "u12",
            "Under-12",
            True,
            50,
            "For children born after August 30th, 2006. All children must be accompanied by an adult.",
            0.2,
            ((None, 0, 0),),
        ),
    ]

    order = 0

    for (
        name,
        display_name,
        has_xfer,
        capacity,
        description,
        vat_rate,
        prices,
    ) in products:
        if Product.get_by_name("general", name):
            continue
        product = Product(
            name=name,
            display_name=display_name,
            capacity_max=capacity,
            description=description,
            parent=general,
            attributes={"is_transferable": has_xfer},
        )

        for index, (price_cap, gbp, eur) in enumerate(prices):
            if len(prices) == 1 or index == 0:
                tier_name = name + "-std"
                active = True

            elif index == 1:
                tier_name = name + "-early-bird"
                active = False

            elif index == 2:
                tier_name = name + "-late"
                active = False

            if PriceTier.get_by_name("general", "name", tier_name):
                continue

            pt = PriceTier(
                name=tier_name,
                capacity_max=price_cap,
                personal_limit=10,
                vat_rate=vat_rate,
                parent=product,
                active=active,
            )
            Price(currency="GBP", price_int=gbp * 100, price_tier=pt)
            Price(currency="EUR", price_int=eur * 100, price_tier=pt)

        ProductViewProduct(view, product, order)
        order += 1

    db.session.flush()

    misc = [
        # name, display_name, cap, personal_limit, gbp, eur, description, vat_rate
        (
            "parking",
            "Parking Ticket",
            1700,
            4,
            15,
            21,
            "We're trying to keep cars to a minimum. Please take public transport or car-share if you can.",
            0.2,
        ),
        (
            "campervan",
            "Caravan/\u200cCampervan Ticket",
            60,
            2,
            30,
            42,
            "If you bring a caravan, you won't need a separate parking ticket for the towing car.",
            0.2,
        ),
    ]

    order = 0
    for name, display_name, cap, personal_limit, gbp, eur, description, vat_rate in misc:
        if Product.get_by_name(name, name):
            continue

        group = ProductGroup.get_by_name(name)
        product = Product(
            name=name, display_name=display_name, description=description, parent=group
        )
        pt = PriceTier(name=name, personal_limit=personal_limit, parent=product, vat_rate=vat_rate)
        db.session.add(pt)
        db.session.add(Price(currency="GBP", price_int=gbp * 100, price_tier=pt))
        db.session.add(Price(currency="EUR", price_int=eur * 100, price_tier=pt))

        ProductViewProduct(view, product, order)
        order += 1

    db.session.commit()

    # ('t-shirt', 'T-Shirt', 200, 10, 10, 12, "Pre-order the official Electromagnetic Field t-shirt. T-shirts will be available to collect during the event."),


@tickets.cli.command("create")
def create():
    """Create tickets structure from hardcoded data"""
    create_product_groups()


@tickets.cli.command("create_merch")
def create_merch():
    merch_group = ProductGroup.get_by_name("merchandise")

    tees_group = ProductGroup.get_by_name("tees")
    if not tees_group:
        tees_group = ProductGroup(name="tees", parent=merch_group)
        db.session.add(tees_group)
    tees_view = ProductView.get_by_name("tees")
    if not tees_view:
        tees_view = ProductView(name="tees", type="tees")
        db.session.add(tees_view)

    badge_group = ProductGroup.get_by_name("badge")
    if not badge_group:
        badge_group = ProductGroup(name="badge", parent=merch_group)
        db.session.add(badge_group)
    badge_view = ProductView.get_by_name("badge")
    if not badge_view:
        badge_view = ProductView(name="badge", type="badge")
        db.session.add(badge_view)

    db.session.flush()

    badge_def = [
        # name, display_name, personal_limit, gbp, eur, description, vat_rate
        (
            "tildagon",
            "Tildagon",
            4,
            10,
            11.70,
            "One badge without a battery",
            0.2,
        ),
        (
            "tildagon-battery",
            "Tildagon battery",
            4,
            3,
            3.50,
            "If you have a TiLDA badge battery from EMF 2016 or EMF 2018 (not EMF 2022), it will work with Tildagon.",
            0.2,
        ),
    ]

    order = 0
    for name, display_name, personal_limit, gbp, eur, description, vat_rate in badge_def:
        if Product.get_by_name(badge_group.name, name):
            continue

        product = Product(
            name=name, display_name=display_name, description=description, parent=badge_group
        )
        pt = PriceTier(name=name, parent=product, vat_rate=vat_rate)
        db.session.add(pt)
        db.session.add(Price(currency="GBP", price_int=gbp * 100, price_tier=pt))
        db.session.add(Price(currency="EUR", price_int=eur * 100, price_tier=pt))

        ProductViewProduct(badge_view, product, order)
        order += 1

    # name, display_name, GBP, EUR
    shirt_types = [
        (f"unisex-{size}", f"Unisex T-shirt ({size})", 12, 14) for size in ["small", "medium", "large", "XL", "2XL", "3XL", "4XL", "5XL"]
    ] + [
        (f"womens-{size}", f"Womens T-shirt ({size})", 12, 14) for size in ["small", "medium", "large", "XL", "2XL"]
    ] + [
        (f"kids-{ages}", f"Kids T-shirt (age {ages})", 6, 7) for ages in ["3-4", "5-6", "7-8", "9-11", "12-13"]
    ]

    order = 0
    for name, display_name, gbp, eur in shirt_types:
        if Product.get_by_name(tees_group.name, name):
            continue

        product = Product(
            name=name, display_name=display_name, parent=tees_group
        )
        pt = PriceTier(name=name, parent=product, vat_rate=vat_rate)
        db.session.add(pt)
        db.session.add(Price(currency="GBP", price_int=gbp * 100, price_tier=pt))
        db.session.add(Price(currency="EUR", price_int=eur * 100, price_tier=pt))

        ProductViewProduct(tees_view, product, order)
        order += 1

    db.session.commit()


@scheduled_task(minutes=30)
def expire_reserved():
    """Expire reserved tickets"""

    if (
        feature_enabled("STRIPE")
        and not feature_enabled("BANK_TRANSFER")
        and not feature_enabled("BANK_TRANSFER_EURO")
    ):
        # Things are moving quickly now, only let people reserve tickets for an hour
        stalled_payment_grace_period = timedelta(hours=1)

    else:
        stalled_payment_grace_period = timedelta(days=3)

    app.logger.info(
        "Cancelling reserved tickets with grace period %s", stalled_payment_grace_period
    )

    # Payments where someone started the process but didn't complete
    payments = (
        Purchase.query.filter(
            Purchase.state == "reserved",
            Purchase.modified < datetime.utcnow() - stalled_payment_grace_period,
            ~Purchase.payment_id.is_(None),
        )
        .join(Payment)
        .with_entities(Payment)
        .group_by(Payment)
    )

    for payment in payments:
        payment.lock()

        if payment.state == "charging":
            # This should only happen if webhooks aren't getting through
            app.logger.error("Not cancelling payment %s", payment.id)
            continue

        app.logger.info("Cancelling payment %s", payment.id)
        assert payment.state == "new" and payment.provider in {"stripe"}
        payment.cancel()

    # Purchases that were added to baskets but not checked out
    # This should match the wording in templates/tickets/_basket.html
    incomplete_purchase_grace_period = timedelta(hours=1)

    purchases = Purchase.query.filter(
        Purchase.state == "reserved",
        Purchase.modified < datetime.utcnow() - incomplete_purchase_grace_period,
        Purchase.payment_id.is_(None),
    )
    for purchase in purchases:
        app.logger.info("Cancelling purchase %s", purchase.id)
        purchase.cancel()

    # Purchases reserved by admins
    admin_reservation_grace_period = timedelta(days=3)

    purchases = Purchase.query.filter(
        Purchase.state == "admin-reserved",
        Purchase.modified < datetime.utcnow() - admin_reservation_grace_period,
        Purchase.payment_id.is_(None),
    )
    for purchase in purchases:
        app.logger.info("Cancelling purchase %s", purchase.id)
        purchase.cancel()

    db.session.commit()


@tickets.cli.command("email_transfer_reminders")
def email_transfer_reminders():
    pass
    # users_to_email = User.query.join(Ticket, TicketType).filter(
    #     TicketType.admits == 'full',
    #     Ticket.paid == True,  # noqa: E712
    #     Ticket.transfer_reminder_sent == False,
    # ).group_by(User).having(func.count() > 1)

    # for user in users_to_email:
    #     msg = EmailMessage("Your Electromagnetic Field Tickets",
    #         from_email=from_email('TICKETS_EMAIL'),
    #         to=[user.email]
    #     )

    #     msg.body = render_template("emails/transfer-reminder.txt", user=user)

    #     app.logger.info('Emailing %s transfer reminder', user.email)
    #     msg.send()

    #     for ticket in user.tickets:
    #         ticket.transfer_reminder_sent = True
    #     db.session.commit()


@tickets.cli.command("email_tickets")
def email_tickets():
    """Email tickets to those who haven't received them"""
    users_purchase_counts = (
        Purchase.query.filter_by(is_paid_for=True, state="paid")
        .join(PriceTier, Product, ProductGroup)
        .filter(ProductGroup.type.in_(RECEIPT_TYPES))
        .join(Purchase.owner)
        .with_entities(User, func.count(Purchase.id))
        .group_by(User)
        .order_by(User.id)
    )

    for user, purchase_count in users_purchase_counts:
        plural = purchase_count != 1 and "s" or ""

        msg = EmailMessage(
            "Your Electromagnetic Field Ticket%s" % plural,
            from_email=from_email("TICKETS_EMAIL"),
            to=[user.email],
        )

        already_emailed = set_tickets_emailed(user)
        msg.body = render_template(
            "emails/receipt.txt", user=user, already_emailed=already_emailed
        )

        attach_tickets(msg, user)

        app.logger.info(
            "Emailing %s receipt for %s tickets", user.email, purchase_count
        )
        msg.send()

        db.session.commit()
