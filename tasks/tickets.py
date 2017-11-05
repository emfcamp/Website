# coding=utf-8

from datetime import datetime

from flask import current_app as app # , render_template
from flask_script import Command
# from flask_mail import Message
# from sqlalchemy import or_, func
# from sqlalchemy.orm.exc import NoResultFound

from main import db # mail,
# from apps.common.receipt import attach_tickets
from models.product import ProductGroup, Product, PriceTier, Price
# from models.ticket import Ticket, TicketPrice, TicketType
# from models.user import User



def create_product_groups():
    # FIXME might be worth creating separate sub-classes for site-capacity & allocations
    site_capacity = ProductGroup(name='Admission Tickets',
                                 type='admission_ticket',
                                 expires=datetime(2018, 9, 3),
                                 capacity_max=app.config.get('MAXIMUM_ADMISSIONS'))
    db.session.add(site_capacity)
    db.session.commit()

    allocations = (
        # name, capacity
        ('Vendors', 100),
        ('Sponsors', 200),
        ('Speakers', 100),
        ('General', None),
    )

    for name, capacity in allocations:
        if ProductGroup.get_by_name(name):
            continue
        pg = ProductGroup(name=name, capacity_max=capacity, parent=site_capacity)
        db.session.add(pg)
    db.session.commit()

    general = ProductGroup.get_by_name('General')

    attendee_types = (
        # name, display name, transferable, badge, capacity, description, (early cap, gbp, eur), (std cap, gbp eur), (late cap, gbp, eur)
        ('full', 'Full Camp Ticket', True, True, None, 'Full ticket',
            ((250, 105, 125), (1500, 115, 135), (None, 125, 145))
        ),
        ('full-s', 'Full Camp Ticket (Supporter)', True, True, None, 'Support this non-profit event by paying a bit more. All money will go towards making EMF more awesome.',
            ((None, 150, 180),)
        ),
        ('full-sg', 'Full Camp Ticket (Gold Supporter)', True, True, None, 'Support this non-profit event by paying a bit more. All money will go towards making EMF more awesome.',
            ((None, 200, 240),)
        ),
        ('u5', 'Under-5', True, False, 50, 'For children born after August 31st, 2013. All children must be accompanied by an adult.',
            ((None, 0, 0),)
        ),
        ('u16', 'Under-16', True, False, 150, 'For visitors born after August 5th, 2000. All under-16s must be accompanied by an adult.',
            ((None, 55, 63),)
        ),
    )

    for order, (name, display_name, has_xfer, has_badge, capacity, description, prices) in enumerate(attendee_types):
        if Product.get_by_name(name):
            continue
        pg = Product(name=name, display_name=display_name, capacity_max=capacity,
                     description=description, parent=general,
                     attributes={'is_transferable': has_xfer,
                                 'has_badge': has_badge})
        db.session.add(pg)

        for index, (price_cap, gbp, eur) in enumerate(prices):
            if len(prices) == 1:
                tier_name = name + '-std'

            elif index == 0:
                tier_name = name + '-early-bird'
            elif index == 1:
                tier_name = name + '-std'
            elif index == 2:
                tier_name = name + '-late'

            if ProductGroup.get_by_name(tier_name):
                continue

            pt = PriceTier(name=tier_name, capacity_max=price_cap, personal_limit=10, parent=pg)
            db.session.add(pt)
            db.session.add(Price(currency='gbp', price_int=gbp * 100, price_tier=pt))
            db.session.add(Price(currency='eur', price_int=eur * 100, price_tier=pt))

    db.session.commit()

    misc = (
        # name, display_name, cap, personal_limit, gbp, eur, description
        ('car', 'Parking Ticket', 1700, 4, 15, 21, "We're trying to keep cars to a minimum. Please take public transport or car-share if you can."),
        ('campervan', 'Caravan/\u200cCampervan Ticket', 60, 2, 30, 42, "If you bring a caravan, you won't need a separate parking ticket for the towing car."),
    )

    parking_pg = ProductGroup(name='Parking',
                        expires=datetime(2018, 9, 3))


    for name, display_name, cap, personal_limit, gbp, eur, description in misc:
        ticket = Product(name=name, display_name=display_name, description=description, parent=parking_pg)
        pt = PriceTier(name=name, personal_limit=personal_limit,
                       parent=ticket)
        db.session.add(pt)
        db.session.add(Price(currency='gbp', price_int=gbp * 100, price_tier=pt))
        db.session.add(Price(currency='eur', price_int=eur * 100, price_tier=pt))

    db.session.commit()

    # ('t-shirt', 'T-Shirt', 200, 10, 10, 12, "Pre-order the official Electromagnetic Field t-shirt. T-shirts will be available to collect during the event."),

class CreateTickets(Command):
    def run(self):
        create_product_groups()


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
