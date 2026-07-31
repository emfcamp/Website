from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import click
import googleapiclient.errors
from flask import current_app as app
from flask import render_template
from flask_mailman import EmailMessage
from sqlalchemy import func, select

from apps.common import feature_enabled, walletpass
from apps.common.receipt import RECEIPT_TYPES, attach_tickets, set_tickets_emailed
from apps.payments.refund import create_stripe_refund
from main import db
from models import Currency, naive_utcnow
from models.payment import Payment, StripePayment
from models.product import (
    Price,
    PriceTier,
    Product,
    ProductGroup,
    ProductView,
    ProductViewProduct,
)
from models.purchase import Purchase
from models.scheduled_task import scheduled_task
from models.user import User

from ..config import config
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
        pg = ProductGroup(
            name=name,
            type=name,
            capacity_max=capacity,
            expires=expires,
            attributes={"is_redeemable": redeemable},
        )
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
        db.session.add(ProductGroup(name=name, capacity_max=capacity, parent=admissions))

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
        db.session.add(product)

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
            db.session.add(pt)
            db.session.add(Price(currency="GBP", price_int=gbp * 100, price_tier=pt))
            db.session.add(Price(currency="EUR", price_int=eur * 100, price_tier=pt))

        db.session.add(ProductViewProduct(view, product, order))
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
    for name, display_name, _cap, personal_limit, gbp, eur, description, vat_rate in misc:
        if Product.get_by_name(name, name):
            continue

        group = ProductGroup.get_by_name(name)
        product = Product(name=name, display_name=display_name, description=description, parent=group)
        db.session.add(product)
        pt = PriceTier(name=name, personal_limit=personal_limit, parent=product, vat_rate=vat_rate)
        db.session.add(pt)
        db.session.add(Price(currency="GBP", price_int=gbp * 100, price_tier=pt))
        db.session.add(Price(currency="EUR", price_int=eur * 100, price_tier=pt))

        db.session.add(ProductViewProduct(view, product, order))
        order += 1

    db.session.commit()

    # The speakers product view is required for the CfP round close flow (to issue tickets from)
    speaker_view = ProductView.get_by_name("speakers")
    if not speaker_view:
        speaker_view = ProductView(name="speakers", cfp_accepted_only=True, type="ticket")
        db.session.add(speaker_view)
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
    for name, display_name, _personal_limit, gbp, eur, description, vat_rate in badge_def:
        if Product.get_by_name(badge_group.name, name):
            continue

        product = Product(name=name, display_name=display_name, description=description, parent=badge_group)
        db.session.add(product)
        pt = PriceTier(name=name, parent=product, vat_rate=vat_rate)
        db.session.add(pt)
        db.session.add(Price(currency="GBP", price_int=gbp * 100, price_tier=pt))
        db.session.add(Price(currency="EUR", price_int=eur * 100, price_tier=pt))

        db.session.add(ProductViewProduct(badge_view, product, order))
        order += 1

    # name, display_name, GBP, EUR
    shirt_types = (
        [
            (f"unisex-{size}", f"Unisex T-shirt ({size})", 12, 14)
            for size in ["small", "medium", "large", "XL", "2XL", "3XL", "4XL", "5XL"]
        ]
        + [
            (f"womens-{size}", f"Womens T-shirt ({size})", 12, 14)
            for size in ["small", "medium", "large", "XL", "2XL"]
        ]
        + [
            (f"kids-{ages}", f"Kids T-shirt (age {ages})", 6, 7)
            for ages in ["3-4", "5-6", "7-8", "9-11", "12-13"]
        ]
    )

    order = 0
    for name, display_name, gbp, eur in shirt_types:
        if Product.get_by_name(tees_group.name, name):
            continue

        product = Product(name=name, display_name=display_name, parent=tees_group)
        db.session.add(product)
        pt = PriceTier(name=name, parent=product, vat_rate=vat_rate)
        db.session.add(pt)
        db.session.add(Price(currency="GBP", price_int=gbp * 100, price_tier=pt))
        db.session.add(Price(currency="EUR", price_int=eur * 100, price_tier=pt))

        db.session.add(ProductViewProduct(tees_view, product, order))
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

    app.logger.info("Cancelling reserved tickets with grace period %s", stalled_payment_grace_period)

    # Payments where someone started the process but didn't complete
    payments = (
        Purchase.query.filter(
            Purchase.state == "reserved",
            Purchase.modified < naive_utcnow() - stalled_payment_grace_period,
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
        Purchase.modified < naive_utcnow() - incomplete_purchase_grace_period,
        Purchase.payment_id.is_(None),
    )
    for purchase in purchases:
        app.logger.info("Cancelling purchase %s", purchase.id)
        purchase.cancel()

    # Purchases reserved by admins
    admin_reservation_grace_period = timedelta(days=7)

    purchases = Purchase.query.filter(
        Purchase.state == "admin-reserved",
        Purchase.modified < naive_utcnow() - admin_reservation_grace_period,
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
    #     Ticket.paid == True,
    #     Ticket.transfer_reminder_sent == False,
    # ).group_by(User).having(func.count() > 1)

    # for user in users_to_email:
    #     msg = EmailMessage("Your Electromagnetic Field Tickets",
    #         from_email=config.from_email('TICKETS_EMAIL'),
    #         to=[user.email]
    #     )

    #     msg.body = render_template("emails/transfer-reminder.txt", user=user)

    #     app.logger.info('Emailing %s transfer reminder', user.email)
    #     msg.send()

    #     for ticket in user.tickets:
    #         ticket.transfer_reminder_sent = True
    #     db.session.commit()


@tickets.cli.command("email_tickets")
@click.option("-u", "--user-id", type=int, required=False, help="Email only a specific user")
def email_tickets(user_id: int | None) -> None:
    """Email tickets to those who haven't received them"""
    ctx = app.test_request_context()
    ctx.push()

    if not feature_enabled("ISSUE_TICKETS"):
        app.logger.warning("Not emailing tickets as ISSUE_TICKETS is disabled")
        return

    # This results in the count of un-issued tickets per user.
    # This is what we want for the email subject, but we'll include
    # their previously-emailed tickets in the e-ticket as well.
    # FIXME: this is slightly wrong because it treats merch and hires as
    # a "ticket", but we no longer call those tickets in the actual receipt.
    # We do still want to send out the emails, but we should
    # split out users without admissions tickets and send a different email.
    query = (
        select(User, func.count(Purchase.id))
        .select_from(User)
        .join(User.owned_purchases)
        .where(
            Purchase.ticket_issued == False,
            Purchase.is_paid_for == True,
            Purchase.product.has(Product.parent.has(ProductGroup.type.in_(RECEIPT_TYPES))),
        )
        .group_by(User.id)
        .order_by(User.id)
    )
    if user_id is not None:
        query = query.where(User.id == user_id)

    users_purchase_counts = list(db.session.execute(query).unique())

    for user, purchase_count in users_purchase_counts:
        plural = (purchase_count != 1 and "s") or ""

        msg = EmailMessage(
            f"Your Electromagnetic Field Ticket{plural}",
            from_email=config.from_email("TICKETS_EMAIL"),
            to=[user.email],
        )

        already_emailed = set_tickets_emailed(user)
        msg.body = render_template("emails/receipt.txt", user=user, already_emailed=already_emailed)

        attach_tickets(msg, user)

        app.logger.info("Emailing %s receipt for %s tickets", user.email, purchase_count)
        msg.send()

        db.session.commit()

        if feature_enabled("ISSUE_GOOGLE_WALLET_TICKETS"):
            walletpass.update_gwallet_pass_if_needed(user)


@tickets.cli.command("emf2026_refund_keebdecks")
@click.option(
    "--dry-run", is_flag=True, help="If set, don't actually refund/change the database, just simulate it."
)
def emf2026_refund_keebdecks(dry_run: bool = True) -> None:
    """Perform refunds/part refunds for keebdecks.

    For uncollected keebdecks we provide a full refund.

    For 'part collected' keebdecks (those signed out on Sunday by
    badge@emfcamp.org), we downgrade them to the keebdeck-without-keyboard
    product and provide a part refund.

    We also send appropriate emails to people to let them know what's happened.
    """
    dry_run_prefix = "[DRYRUN] " if dry_run else ""

    ctx = app.test_request_context()
    ctx.push()

    keebdeck_product_name = "badge-keebdeck"
    keebless_name = "badge-keebdeck-without-keyboard"
    keebless = db.session.execute(select(Product).where(Product.name == keebless_name)).scalar_one_or_none()
    assert keebless is not None
    keebless_price: dict[Currency, Price] = {}
    for currency in Currency:
        price = keebless.get_cheapest_price(currency)
        assert price
        keebless_price[currency] = price

    query = (
        select(User)
        .join(User.owned_purchases)
        .where(
            Purchase.is_paid_for == True,
            Purchase.product.has(Product.name == keebdeck_product_name),
        )
        .group_by(User.id)
        .order_by(User.id)
    )

    users = list(db.session.execute(query).unique().scalars())

    def _redeemed_by_badge_on_sunday(purchase: Purchase) -> bool:
        """https://chat.orga.emfcamp.org/emf/pl/wamc3u9kgjfd7nre78w3od98nw"""
        if not purchase.redeemed:
            return False
        redemption_version = purchase.redemption_version()
        assert redemption_version
        redeemer_user: User = redemption_version.transaction.user
        if redeemer_user.email != "badge@emfcamp.org":
            return False
        issued_at_date: date = redemption_version.transaction.issued_at.date()
        return date(2026, 7, 19) == issued_at_date

    for user in users:
        keebdeck_purchases = [
            purchase
            for purchase in user.owned_purchases
            if purchase.is_paid_for and purchase.product.name == keebdeck_product_name
        ]
        part_redeemed_purchases = [
            purchase
            for purchase in keebdeck_purchases
            if purchase.redeemed and _redeemed_by_badge_on_sunday(purchase)
        ]
        uncollected_purchases = [purchase for purchase in keebdeck_purchases if not purchase.redeemed]
        refund_count = len(part_redeemed_purchases) + len(uncollected_purchases)
        if refund_count == 0:
            continue

        if len(uncollected_purchases) == len(keebdeck_purchases):
            refund_type = "full"
        elif len(part_redeemed_purchases) == len(keebdeck_purchases):
            refund_type = "part"
        else:
            refund_type = "complex"

        total_amounts_by_currency: dict[Currency, Decimal] = defaultdict(Decimal)

        app.logger.info(
            "%sRefunding %s for %d keebdecks (%d part-redeemed, %d uncollected)",
            dry_run_prefix,
            user.email,
            refund_count,
            len(part_redeemed_purchases),
            len(uncollected_purchases),
        )

        # Group everything together by payment.
        purchases_by_payment_id: dict[int, tuple[list[Purchase], list[Purchase]]] = defaultdict(
            lambda: ([], [])
        )
        for purchase in part_redeemed_purchases:
            assert purchase.payment_id is not None
            purchases_by_payment_id[purchase.payment_id][0].append(purchase)
        for purchase in uncollected_purchases:
            assert purchase.payment_id is not None
            purchases_by_payment_id[purchase.payment_id][1].append(purchase)
        for payment_id, (part_redeemed_in_payment, uncollected_in_payment) in purchases_by_payment_id.items():
            payment = db.session.execute(select(Payment).where(Payment.id == payment_id)).scalar_one_or_none()
            assert payment
            if not isinstance(payment, StripePayment):
                app.logger.info(
                    "%sCannot refund %s (payment ID %d) -- not a Stripe payment",
                    dry_run_prefix,
                    user.email,
                    payment_id,
                )
                continue
            payment.lock()
            if not payment.is_refundable(ignore_event_refund_state=True):
                app.logger.info(
                    "%sCannot refund %s (payment ID %d) -- payment state is %s",
                    dry_run_prefix,
                    user.email,
                    payment_id,
                    payment.state,
                )
                continue
            payment_refund_amount = Decimal(0)
            for purchase in part_redeemed_in_payment:
                assert purchase.price.currency == payment.currency
                payment_refund_amount += purchase.price.value - keebless_price[payment.currency]
                new_price = keebless_price[payment.currency]
                purchase.price = new_price
                purchase.price_tier = new_price.price_tier
                purchase.product = keebless
            for purchase in uncollected_in_payment:
                assert purchase.price.currency == payment.currency
                payment_refund_amount += purchase.price.value
                purchase.set_state("refunded")
            total_amounts_by_currency[payment.currency] += payment_refund_amount
            app.logger.info(
                "%sRefunding %s (payment ID %d) for %d part-redeemed, %d uncollected keebdecks -- refunding %s %s",
                dry_run_prefix,
                user.email,
                payment_id,
                len(part_redeemed_purchases),
                len(uncollected_purchases),
                payment_refund_amount,
                payment.currency,
            )
            if not dry_run:
                refund = create_stripe_refund(
                    payment,
                    payment_refund_amount,
                    {
                        "type": "keebdeck-refund",
                        "part-redeemed": ",".join(str(p.id) for p in part_redeemed_in_payment),
                        "uncollected": ",".join(str(p.id) for p in uncollected_in_payment),
                    },
                )
                db.session.add(refund)
            payment.state = "refunded" if payment_refund_amount == payment.amount else "partrefunded"

        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()

        msg = EmailMessage(
            "Your Electromagnetic Field Keyboard Hexpansion Refund",
            from_email=config.from_email("TICKETS_EMAIL"),
            to=[user.email],
        )

        refund_total_formatted = " and ".join(
            f"{currency.symbol}{price:.2f}" for currency, price in total_amounts_by_currency.items()
        )
        assert refund_total_formatted
        msg.body = render_template(
            "emails/emf2026-keebdeck-refund.txt",
            user=user,
            refund_type=refund_type,
            refund_count=refund_count,
            refund_total=refund_total_formatted,
        )

        app.logger.info("%sEmailing %s keebdeck refund notification", dry_run_prefix, user.email)
        if not dry_run:
            msg.send()


@tickets.cli.group()
def googlewallet():
    pass


@googlewallet.command()
def create_or_update_class():
    """Create or update the base ticket class. This needs to be run before issuing Google Wallet tickets."""
    ctx = app.test_request_context()
    ctx.push()

    client = walletpass.gwallet_api_client().eventticketclass()
    new_class = walletpass.generate_gwallet_class()
    # Check if it exists already:
    existing_class = None
    try:
        existing_class = client.get(resourceId=new_class["id"]).execute()
    except googleapiclient.errors.HttpError as e:
        if e.resp.status != 404:
            raise
    if existing_class:
        app.logger.info("Updating existing Google Wallet ticket class %s", new_class["id"])
        client.update(resourceId=new_class["id"], body=new_class).execute()
    else:
        app.logger.info("Creating new Google Wallet ticket class %s", new_class["id"])
        client.insert(body=new_class).execute()


@googlewallet.command()
@click.option("--email", help="User to build the pass for.")
def ticket_url(email):
    """Creates a URL for adding a user's passes to their wallet. Useful for testing before enabling the feature flag for everyone."""
    ctx = app.test_request_context()
    ctx.push()

    if not email:
        raise click.ClickException("--email must be specified.")
    user = User.query.filter_by(email=email).one()
    if user is None:
        raise click.ClickException(f"No user {email} found.")

    click.echo(user.google_wallet_pass_url)


@googlewallet.command()
@click.option("--email", help="User to update the pass for.")
@click.option("--all-users", is_flag=True, help="Update all Google Wallet passes.")
def update_pass(email, all_users):
    """Pushes an update to a given user's pass. Won't create it if it doesn't already exist (i.e. the user hasn't clicked the link)."""
    ctx = app.test_request_context()
    ctx.push()

    if not email and not all_users:
        raise click.ClickException("--email or --all-users must be specified.")

    client = walletpass.gwallet_api_client()

    if email:
        user = User.get_by_email(email)
        if user is None:
            raise click.ClickException(f"No user {email} found.")

        new_pass = walletpass.generate_gwallet_pass(user)

        old_pass = walletpass.get_old_gwallet_pass(client, new_pass)
        if not old_pass:
            click.echo(f"User {user.email} has no ticket in Google Wallet's backend.")

        walletpass.update_gwallet_pass(client, user, old_pass, new_pass)

    elif all_users:
        old_passes_by_user_id = walletpass.get_all_gwallet_passes(client)
        user_query = db.select(User).options(db.joinedload(User.buildup_volunteer))
        users = (
            db.session.execute(user_query.filter(User.id.in_(old_passes_by_user_id.keys())))
            .unique()
            .scalars()
        )

        for user in users:
            for old_pass in old_passes_by_user_id[user.id]:
                new_pass = walletpass.generate_gwallet_pass(user)
                walletpass.update_gwallet_pass(client, user, old_pass, new_pass)
