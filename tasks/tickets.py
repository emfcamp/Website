from datetime import datetime, timedelta

from flask import current_app as app, render_template
from flask_mail import Message
from flask_script import Command
from sqlalchemy import func

from main import db, mail
from apps.common import feature_enabled
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
from models.purchase import Purchase
from models.user import User


def create_product_groups():
    top_level_groups = [
        # name, capacity, expires
        ("admissions", None, 2500),
        ("parking", None, None),
        ("campervan", None, None),
        ("merchandise", None, None),
    ]
    for name, expires, capacity in top_level_groups:
        if ProductGroup.get_by_name(name):
            continue
        pg = ProductGroup(name=name, type=name, capacity_max=capacity, expires=expires)
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
        # name, display name, transferable, badge, capacity, description, (std cap, gbp eur), (early cap, gbp, eur), (late cap, gbp, eur)
        (
            "full",
            "Full Camp Ticket",
            True,
            True,
            None,
            "Full ticket",
            ((1500, 115, 135), (250, 105, 125), (None, 125, 145)),
        ),
        (
            "full-s",
            "Full Camp Ticket (Supporter)",
            True,
            True,
            None,
            "Support this non-profit event by paying a bit more. All money will go towards making EMF more awesome.",
            ((None, 150, 180),),
        ),
        (
            "full-sg",
            "Full Camp Ticket (Gold Supporter)",
            True,
            True,
            None,
            "Support this non-profit event by paying a bit more. All money will go towards making EMF more awesome.",
            ((None, 200, 240),),
        ),
        (
            "u18",
            "Under-18",
            True,
            False,
            150,
            "For visitors born after August 30th, 2000. All under-18s must be accompanied by an adult.",
            ((None, 55, 63),),
        ),
        (
            "u12",
            "Under-12",
            True,
            False,
            50,
            "For children born after August 30th, 2006. All children must be accompanied by an adult.",
            ((None, 0, 0),),
        ),
    ]

    order = 0

    for (
        name,
        display_name,
        has_xfer,
        has_badge,
        capacity,
        description,
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
            attributes={"is_transferable": has_xfer, "has_badge": has_badge},
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
                parent=product,
                active=active,
            )
            Price(currency="GBP", price_int=gbp * 100, price_tier=pt)
            Price(currency="EUR", price_int=eur * 100, price_tier=pt)

        ProductViewProduct(view, product, order)
        order += 1

    db.session.flush()

    misc = [
        # name, display_name, cap, personal_limit, gbp, eur, description
        (
            "parking",
            "Parking Ticket",
            1700,
            4,
            15,
            21,
            "We're trying to keep cars to a minimum. Please take public transport or car-share if you can.",
        ),
        (
            "campervan",
            "Caravan/\u200cCampervan Ticket",
            60,
            2,
            30,
            42,
            "If you bring a caravan, you won't need a separate parking ticket for the towing car.",
        ),
    ]

    for name, display_name, cap, personal_limit, gbp, eur, description in misc:
        if Product.get_by_name(name, name):
            continue

        group = ProductGroup.get_by_name(name)
        product = Product(
            name=name, display_name=display_name, description=description, parent=group
        )
        pt = PriceTier(name=name, personal_limit=personal_limit, parent=product)
        db.session.add(pt)
        db.session.add(Price(currency="GBP", price_int=gbp * 100, price_tier=pt))
        db.session.add(Price(currency="EUR", price_int=eur * 100, price_tier=pt))

        ProductViewProduct(view, product, order)
        order += 1

    db.session.commit()

    # ('t-shirt', 'T-Shirt', 200, 10, 10, 12, "Pre-order the official Electromagnetic Field t-shirt. T-shirts will be available to collect during the event."),


class CreateTickets(Command):
    def run(self):
        create_product_groups()


class CancelReservedTickets(Command):
    def run(self):

        if (
            feature_enabled("STRIPE")
            and not feature_enabled("BANK_TRANSFER")
            and not feature_enabled("BANK_TRANSFER_EURO")
            and not feature_enabled("GOCARDLESS")
            and not feature_enabled("GOCARDLESS_EURO")
        ):
            # Things are moving quickly now, only let people reserve tickets for an hour
            grace_period = timedelta(hours=1)

        else:
            grace_period = timedelta(days=3)

        app.logger.info(
            "Cancelling reserved tickets with grace period %s", grace_period
        )

        # Payments where someone started the process but didn't complete
        payments = (
            Purchase.query.filter(
                Purchase.state == "reserved",
                Purchase.modified < datetime.utcnow() - grace_period,
                ~Purchase.payment_id.is_(None),
            )
            .join(Payment)
            .with_entities(Payment)
            .group_by(Payment)
        )

        for payment in payments:
            payment.lock()
            app.logger.info("Cancelling payment %s", payment.id)
            assert payment.state == "new" and payment.provider in {
                "gocardless",
                "stripe",
            }
            payment.cancel()

        # Purchases that were added to baskets but not checked out
        purchases = Purchase.query.filter(
            Purchase.state == "reserved",
            Purchase.modified < datetime.utcnow() - grace_period,
            Purchase.payment_id.is_(None),
        )
        for purchase in purchases:
            app.logger.info("Cancelling purchase %s", purchase.id)
            purchase.cancel()

        db.session.commit()


class SendTransferReminder(Command):
    def run(self):
        pass
        # users_to_email = User.query.join(Ticket, TicketType).filter(
        #     TicketType.admits == 'full',
        #     Ticket.paid == True,  # noqa: E712
        #     Ticket.transfer_reminder_sent == False,
        # ).group_by(User).having(func.count() > 1)

        # for user in users_to_email:
        #     msg = Message("Your Electromagnetic Field Tickets",
        #                   sender=app.config['TICKETS_EMAIL'],
        #                   recipients=[user.email])

        #     msg.body = render_template("emails/transfer-reminder.txt", user=user)

        #     app.logger.info('Emailing %s transfer reminder', user.email)
        #     mail.send(msg)

        #     for ticket in user.tickets:
        #         ticket.transfer_reminder_sent = True
        #     db.session.commit()


class SendTickets(Command):
    def run(self):
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

            msg = Message(
                "Your Electromagnetic Field Ticket%s" % plural,
                sender=app.config["TICKETS_EMAIL"],
                recipients=[user.email],
            )

            already_emailed = set_tickets_emailed(user)
            msg.body = render_template(
                "emails/receipt.txt", user=user, already_emailed=already_emailed
            )

            attach_tickets(msg, user)

            app.logger.info(
                "Emailing %s receipt for %s tickets", user.email, purchase_count
            )
            mail.send(msg)

            db.session.commit()
