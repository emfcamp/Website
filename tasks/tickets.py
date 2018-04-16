# coding=utf-8

from datetime import datetime, timedelta

from flask import current_app as app
from flask_script import Command
from main import db
from models.payment import Payment
from models.product import ProductGroup, Product, PriceTier, Price, ProductView, ProductViewProduct
from models.purchase import Purchase


def create_product_groups():
    top_level_groups = [
        # name, capacity, expires
        ('admissions', datetime(2018, 9, 3), app.config.get('MAXIMUM_ADMISSIONS')),
        ('parking', datetime(2018, 9, 3), None),
        ('campervan', datetime(2018, 9, 3), None),
        ('merchandise', datetime(2018, 8, 12), None),
    ]
    for name, expires, capacity in top_level_groups:
        if ProductGroup.get_by_name(name):
            continue
        pg = ProductGroup(name=name, type=name, capacity_max=capacity, expires=expires)
        db.session.add(pg)

    allocations = [
        # name, capacity
        ('vendors', 100),
        ('sponsors', 200),
        ('speakers', 100),
        ('general', 800),
    ]

    admissions = ProductGroup.get_by_name('admissions')
    for name, capacity in allocations:
        if ProductGroup.get_by_name(name):
            continue
        ProductGroup(name=name, capacity_max=capacity, parent=admissions)

    view = ProductView.get_by_name('main')
    if not view:
        view = ProductView('main')
        db.session.add(view)

    db.session.flush()

    general = ProductGroup.get_by_name('general')

    products = [
        # name, display name, transferable, badge, capacity, description, (std cap, gbp eur), (early cap, gbp, eur), (late cap, gbp, eur)
        ('full', 'Full Camp Ticket', True, True, None, 'Full ticket',
            ((1500, 115, 135), (250, 105, 125), (None, 125, 145))
        ),
        ('full-s', 'Full Camp Ticket (Supporter)', True, True, None, 'Support this non-profit event by paying a bit more. All money will go towards making EMF more awesome.',
            ((None, 150, 180),)
        ),
        ('full-sg', 'Full Camp Ticket (Gold Supporter)', True, True, None, 'Support this non-profit event by paying a bit more. All money will go towards making EMF more awesome.',
            ((None, 200, 240),)
        ),
        ('u18', 'Under-18', True, False, 150, 'For visitors born after August 30th, 2000. All under-18s must be accompanied by an adult.',
            ((None, 55, 63),)
        ),
        ('u12', 'Under-12', True, False, 50, 'For children born after August 30th, 2006. All children must be accompanied by an adult.',
            ((None, 0, 0),)
        ),
    ]

    order = 0

    for name, display_name, has_xfer, has_badge, capacity, description, prices in products:
        if Product.get_by_name('general', name):
            continue
        product = Product(name=name, display_name=display_name, capacity_max=capacity,
                     description=description, parent=general,
                     attributes={'is_transferable': has_xfer,
                                 'has_badge': has_badge})

        for index, (price_cap, gbp, eur) in enumerate(prices):
            if len(prices) == 1 or index == 0:
                tier_name = name + '-std'
                active = True

            elif index == 1:
                tier_name = name + '-early-bird'
                active = False

            elif index == 2:
                tier_name = name + '-late'
                active = False

            if PriceTier.get_by_name('general', 'name', tier_name):
                continue

            pt = PriceTier(name=tier_name, capacity_max=price_cap, personal_limit=10, parent=product, active=active)
            Price(currency='GBP', price_int=gbp * 100, price_tier=pt)
            Price(currency='EUR', price_int=eur * 100, price_tier=pt)

        ProductViewProduct(view, product, order)
        order += 1

    db.session.flush()

    misc = [
        # name, display_name, cap, personal_limit, gbp, eur, description
        ('parking', 'Parking Ticket', 1700, 4, 15, 21, "We're trying to keep cars to a minimum. Please take public transport or car-share if you can."),
        ('campervan', 'Caravan/\u200cCampervan Ticket', 60, 2, 30, 42, "If you bring a caravan, you won't need a separate parking ticket for the towing car."),
    ]

    for name, display_name, cap, personal_limit, gbp, eur, description in misc:
        if Product.get_by_name(name, name):
            continue

        group = ProductGroup.get_by_name(name)
        product = Product(name=name, display_name=display_name, description=description, parent=group)
        pt = PriceTier(name=name, personal_limit=personal_limit, parent=product)
        db.session.add(pt)
        db.session.add(Price(currency='GBP', price_int=gbp * 100, price_tier=pt))
        db.session.add(Price(currency='EUR', price_int=eur * 100, price_tier=pt))

        ProductViewProduct(view, product, order)
        order += 1

    db.session.commit()

    # ('t-shirt', 'T-Shirt', 200, 10, 10, 12, "Pre-order the official Electromagnetic Field t-shirt. T-shirts will be available to collect during the event."),

class CreateTickets(Command):
    def run(self):
        create_product_groups()


class CancelReservedTickets(Command):
    def run(self):
        # Payments where someone started the process but didn't complete
        payments = Purchase.query.filter(
            Purchase.state == 'reserved',
            Purchase.modified < datetime.utcnow() - timedelta(days=3),
            ~Purchase.payment_id.is_(None),
        ).join(Payment).with_entities(Payment).group_by(Payment)

        for payment in payments:
            app.logger.info('Cancelling payment %s', payment.id)
            assert payment.state == 'new' and payment.provider in {'gocardless', 'stripe'}
            payment.cancel()

        # Purchases that were added to baskets but not checked out
        purchases = Purchase.query.filter(
            Purchase.state == 'reserved',
            Purchase.modified < datetime.utcnow() - timedelta(days=3),
            Purchase.payment_id.is_(None),
        )
        for purchase in purchases:
            app.logger.info('Cancelling purchase %s', purchase.id)
            purchase.cancel()

        db.session.commit()

class SendTransferReminder(Command):

    def run(self):
        pass
        # users_to_email = User.query.join(Ticket, TicketType).filter(
        #     TicketType.admits == 'full',
        #     Ticket.paid == True,  # noqa
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
        pass
        # paid_items = Ticket.query.filter_by(paid=True).join(TicketType).filter(or_(
        #     TicketType.admits.in_(['full', 'kid', 'car', 'campervan']),
        #     TicketType.fixed_id.in_(range(14, 24))))

        # users = (paid_items.filter(Ticket.emailed == False).join(User)  # noqa
        #                    .group_by(User).with_entities(User).order_by(User.id))

        # for user in users:
        #     user_tickets = Ticket.query.filter_by(paid=True).join(TicketType, User).filter(
        #         TicketType.admits.in_(['full', 'kid', 'car', 'campervan']),
        #         User.id == user.id)

        #     plural = (user_tickets.count() != 1 and 's' or '')

        #     msg = Message("Your Electromagnetic Field Ticket%s" % plural,
        #                   sender=app.config['TICKETS_EMAIL'],
        #                   recipients=[user.email])

        #     msg.body = render_template("emails/receipt.txt", user=user)

        #     attach_tickets(msg, user)

        #     app.logger.info('Emailing %s receipt for %s tickets', user.email, user_tickets.count())
        #     mail.send(msg)

        #     db.session.commit()
