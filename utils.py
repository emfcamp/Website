#!/usr/bin/env python
# coding=utf-8
from datetime import datetime
from dateutil import parser
import ofxparse
import random
import json
from faker import Faker
from collections import OrderedDict

from flask_script import Command, Manager, Option
from flask_migrate import MigrateCommand
from flask import render_template, current_app as app
from flask_mail import Message
from sqlalchemy import or_, func
from sqlalchemy.orm.exc import NoResultFound

from main import create_app, mail, db
from models import (
    User, TicketType, Ticket, TicketPrice, TicketLimitException
)
from models.payment import (
    BankAccount, BankTransaction,
)
from models.permission import Permission
from models.email import EmailJobRecipient
from models.ical import CalendarSource
from apps.payments import banktransfer
from apps.common.receipt import attach_tickets
from slotmachine import SlotMachine

from utils.cfp import (
    ImportCFP, LockProposals, EmailSpeakersAboutSlot,
    EmailSpeakersAboutFinalising, RejectUnacceptedTalks
)


class CreateDB(Command):
    # For testing - you usually want to use db migrate/db upgrade instead
    def run(self):
        db.create_all()


class CreateBankAccounts(Command):
    def run(self):
        gbp = BankAccount('492900', '20716473590526', 'GBP')
        eur = BankAccount('492900', '20716472954433', 'EUR')
        for acct in [gbp, eur]:
            try:
                BankAccount.query.filter_by(acct_id=acct.acct_id, sort_code=acct.sort_code).one()
            except NoResultFound:
                app.logger.info('Adding %s account %s %s', acct.currency, acct.sort_code, acct.acct_id)
                db.session.add(acct)

        db.session.commit()


class LoadOfx(Command):
    option_list = [Option('-f', '--file', dest='filename', help="The .ofx file to load")]

    def run(self, filename):
        ofx = ofxparse.OfxParser.parse(open(filename))

        acct_id = ofx.account.account_id
        sort_code = ofx.account.routing_number
        account = BankAccount.get(sort_code, acct_id)
        if ofx.account.statement.currency.lower() != account.currency.lower():
            app.logger.error("Currency %s doesn't match account currency %s",
                             ofx.account.statement.currency, account.currency)
            return

        added = 0
        duplicate = 0
        dubious = 0

        for txn in ofx.account.statement.transactions:
            if 0 < int(txn.id) < 200101010000000:
                app.logger.debug('Ignoring uncleared transaction %s', txn.id)
                continue
            # date is actually dtposted and is a datetime
            if txn.date < datetime(2015, 1, 1):
                app.logger.debug('Ignoring historic transaction from %s', txn.date)
                continue
            if txn.amount <= 0:
                app.logger.info('Ignoring non-credit transaction for %s', txn.amount)
                continue

            dbtxn = BankTransaction(
                account_id=account.id,
                posted=txn.date,
                type=txn.type,
                amount=txn.amount,
                payee=txn.payee,
                fit_id=txn.id,
            )

            # Check for matching/duplicate transactions.
            # Insert if possible - conflicts can be sorted out within the app.
            matches = dbtxn.get_matching()

            # Euro payments have a blank fit_id
            if dbtxn.fit_id == '00000000':
                # There seems to be a serial in the payee field. Assume that's enough for uniqueness.
                if matches.count():
                    app.logger.debug('Ignoring duplicate transaction from %s', dbtxn.payee)
                    duplicate += 1

                else:
                    db.session.add(dbtxn)
                    added += 1

            else:
                different_fit_ids = matches.filter( BankTransaction.fit_id != dbtxn.fit_id )
                same_fit_ids = matches.filter( BankTransaction.fit_id == dbtxn.fit_id )

                if same_fit_ids.count():
                    app.logger.debug('Ignoring duplicate transaction %s', dbtxn.fit_id)
                    duplicate += 1

                elif BankTransaction.query.filter( BankTransaction.fit_id == dbtxn.fit_id ).count():
                    app.logger.error('Non-matching transactions with same fit_id %s', dbtxn.fit_id)
                    dubious += 1

                elif different_fit_ids.count():
                    app.logger.warn('%s matching transactions with different fit_ids for %s',
                                    different_fit_ids.count(), dbtxn.fit_id)
                    # fit_id may have been changed, so add it anyway
                    db.session.add(dbtxn)
                    added += 1
                    dubious += 1

                else:
                    db.session.add(dbtxn)
                    added += 1

        db.session.commit()
        app.logger.info('Import complete: %s new, %s duplicate, %s dubious',
                        added, duplicate, dubious)


class Reconcile(Command):

    option_list = [Option('-d', '--doit', action='store_true', help="set this to actually change the db")]

    def run(self, doit):
        txns = BankTransaction.query.filter_by(payment_id=None, suppressed=False)

        paid = 0
        failed = 0

        for txn in txns:
            if txn.type.lower() not in ('other', 'directdep'):
                raise ValueError('Unexpected transaction type for %s: %s', txn.id, txn.type)

            if txn.payee.startswith("GOCARDLESS ") or txn.payee.startswith("GC C1 EMF"):
                app.logger.info('Suppressing GoCardless transfer %s', txn.id)
                if doit:
                    txn.suppressed = True
                    db.session.commit()
                continue

            if txn.payee.startswith("STRIPE PAYMENTS EU ") or txn.payee.startswith("STRIPE STRIPE"):
                app.logger.info('Suppressing Stripe transfer %s', txn.id)
                if doit:
                    txn.suppressed = True
                    db.session.commit()
                continue

            app.logger.info("Processing txn %s: %s", txn.id, txn.payee)

            payment = txn.match_payment()
            if not payment:
                app.logger.warn("Could not match payee, skipping")
                failed += 1
                continue

            app.logger.info("Matched to payment %s by %s for %s %s",
                payment.id, payment.user.name, payment.amount, payment.currency)

            if txn.amount != payment.amount:
                app.logger.warn("Transaction amount %s doesn't match %s, skipping",
                                txn.amount, payment.amount)
                failed += 1
                continue

            if txn.account.currency != payment.currency:
                app.logger.warn("Transaction currency %s doesn't match %s, skipping",
                                txn.account.currency, payment.currency)
                failed += 1
                continue

            if payment.state == 'paid':
                app.logger.error("Payment %s has already been paid", payment.id)
                failed += 1
                continue

            if doit:
                txn.payment = payment
                payment.paid()
                db.session.commit()

                banktransfer.send_confirmation(payment)

            app.logger.info("Payment reconciled")
            paid += 1

        app.logger.info('Reconciliation complete: %s paid, %s failed', paid, failed)

def add_ticket_types(types):
    for tt in types:
        try:
            existing_tt = TicketType.query.filter_by(fixed_id=tt.fixed_id).one()

        except NoResultFound:
            app.logger.info('Adding TicketType %s (fixed_id: %s)', tt.name, tt.fixed_id)
            db.session.add(tt)

        else:
            # NB we don't even consider updating prices. If we do, make sure no tickets have been bought.
            app.logger.info('Refreshing TicketType %s (id: %s, fixed_id: %s)', tt.name, existing_tt.id, tt.fixed_id)
            for f in ['name', 'type_limit', 'expires', 'personal_limit', 'order',
                      'has_badge', 'is_transferable', 'description']:
                cur_val = getattr(existing_tt, f)
                new_val = getattr(tt, f)

                if cur_val != new_val:
                    app.logger.info(' %10s: %r -> %r', f, cur_val, new_val)
                    setattr(existing_tt, f, new_val)

        db.session.commit()

    app.logger.info('Tickets refreshed')

def get_main_ticket_types():
    #
    # Update the DB consistently without breaking existing tickets.
    #
    # Ticket prices are immutable, so to change prices, create a new type
    # with a unique id, and set the type limit for the previous one to the
    # number of guaranteed paid tickets (which might be 0).
    #
    # This is fiddly. It should probably be moved out to a json file.

    type_data = [
        # (fixed_id, order, admits, name, type limit, personal limit, GBP, EUR, badge, description, [token, expiry, transferable])
        # Leave order 0 & 1 free for discount tickets
        (12, 1, 'full', 'Full Camp Ticket (Discount Template)', 0, 1, 105.00, 142.00, True, None, 'example', datetime(2016, 8, 1, 12, 0), False),
        (0, 2, 'full', 'Full Camp Ticket', 193, 10, 100.00, 140.00, True, None, None, datetime(2016, 1, 10, 20, 24), True),
        (1, 3, 'full', 'Full Camp Ticket', 350, 10, 110.00, 145.00, True, None, None, datetime(2016, 3, 6, 13, 5), True),
        (2, 4, 'full', 'Full Camp Ticket', 659, 10, 120.00, 158.00, True, None, None, datetime(2016, 7, 24, 0, 0), True),
        (3, 8, 'full', 'Full Camp Ticket (Supporter)', 56, 10, 130.00, 180.00, True,
            "Support this non-profit event by paying a bit more. "
            "All money will go towards making EMF more awesome.",
            None, datetime(2016, 6, 8, 0, 0), True),
        (9, 8, 'full', 'Full Camp Ticket (Supporter)', 140, 10, 130.00, 170.00, True,
            "Support this non-profit event by paying a bit more. "
            "All money will go towards making EMF more awesome.",
            None, datetime(2016, 7, 24, 0, 0), True),

        (4, 9, 'full', 'Full Camp Ticket (Gold Supporter)', 6, 10, 150.00, 210.00, True,
            "Pay even more, receive our undying gratitude.",
            None, datetime(2016, 6, 8, 0, 0), True),
        (10, 9, 'full', 'Full Camp Ticket (Gold Supporter)', 45, 10, 150.00, 195.00, True,
            "Pay even more, receive our undying gratitude.",
            None, datetime(2016, 7, 24, 0, 0), True),

        (5, 10, 'kid', 'Under-16 Camp Ticket', 11, 10, 45.00, 64.00, True,
            "For visitors born after August 5th, 2000. "
            "All under-16s must be accompanied by an adult.",
            None, datetime(2016, 6, 8, 0, 0), True),
        (11, 10, 'kid', 'Under-16 Camp Ticket', 500, 80, 45.00, 60.00, True,
            "For visitors born after August 5th, 2000. "
            "All under-16s must be accompanied by an adult.",
            None, datetime(2016, 8, 4, 0, 0), True),

        (6, 15, 'kid', 'Under-5 Camp Ticket', 35, 4, 0, 0, False,
            "For children born after August 5th, 2011. "
            "All children must be accompanied by an adult.",
            None, datetime(2016, 8, 4, 0, 0), True),

        (13, 25, 'other',
            'Tent (Template)', 0, 1, 300.00, 400.00, False,
            "Pre-ordered village tents will be placed on site before the event starts.",
            'example', datetime(2016, 7, 1, 12, 0), True),

        (14, 30, 'other',
            "Semi-fitted T-Shirt - S", 200, 10, 10.00, 12.00, False,
            "Pre-order the official Electromagnetic Field t-shirt. T-shirts will be available to collect during the event.",
            None, datetime(2016, 7, 15, 0, 0), False),
        (15, 31, 'other', "Semi-fitted T-Shirt - M", 200, 10, 10.00, 12.00, False, None, None, datetime(2016, 7, 15, 0, 0), False),
        (16, 32, 'other', "Semi-fitted T-Shirt - L", 200, 10, 10.00, 12.00, False, None, None, datetime(2016, 7, 15, 0, 0), False),
        (17, 33, 'other', "Semi-fitted T-Shirt - XL", 200, 10, 10.00, 12.00, False, None, None, datetime(2016, 7, 15, 0, 0), False),
        (18, 34, 'other', "Semi-fitted T-Shirt - XXL", 200, 10, 10.00, 12.00, False, None, None, datetime(2016, 7, 15, 0, 0), False),
        (19, 35, 'other', "Unfitted T-Shirt - S", 200, 10, 10.00, 12.00, False, None, None, datetime(2016, 7, 15, 0, 0), False),
        (20, 36, 'other', "Unfitted T-Shirt - M", 200, 10, 10.00, 12.00, False, None, None, datetime(2016, 7, 15, 0, 0), False),
        (21, 37, 'other', "Unfitted T-Shirt - L", 200, 10, 10.00, 12.00, False, None, None, datetime(2016, 7, 15, 0, 0), False),
        (22, 38, 'other', "Unfitted T-Shirt - XL", 200, 10, 10.00, 12.00, False, None, None, datetime(2016, 7, 15, 0, 0), False),
        (23, 39, 'other', "Unfitted T-Shirt - XXL", 200, 10, 10.00, 12.00, False, None, None, datetime(2016, 7, 15, 0, 0), False),

        (7, 50, 'car', 'Parking Ticket', 700, 4, 15.00, 21.00, False,
            "We're trying to keep cars to a minimum. "
            "Please take public transport or car-share if you can.",
            None, None, True),

        (24, 50, 'car', 'Parking Ticket (Cash)', 700, 4, 0, 0, False,
            "We're trying to keep cars to a minimum. "
            "Please take public transport or car-share if you can.",
            None, None, True),

        (8, 55, 'campervan',
            u'Caravan/\u200cCampervan Ticket', 60, 2, 30.00, 42.00, False,
            "If you bring a caravan, you won't need a separate parking ticket for the towing car.",
            None, None, True),
    ]
    # most of these tickets have no tokens or expiry dates
    assert all([len(t) == 13 for t in type_data])

    types = []
    for row in type_data:
        tt = TicketType(*row[1:5], personal_limit=row[5], description=row[9],
            has_badge=row[8], discount_token=row[10], expires=row[11],
            is_transferable=row[12])
        tt.fixed_id = row[0]
        tt.prices = [TicketPrice('GBP', row[6]), TicketPrice('EUR', row[7])]
        types.append(tt)

    return types

def test_main_ticket_types():
    # Test things like non-unique keys
    types = get_main_ticket_types()
    fixed_ids = [tt.fixed_id for tt in types]
    if len(set(fixed_ids)) < len(fixed_ids):
        raise Exception('Duplicate ticket type fixed_id')


class CreateTickets(Command):
    def run(self):
        types = get_main_ticket_types()
        add_ticket_types(types)


class SendTransferReminder(Command):

    def run(self):
        users_to_email = User.query.join(Ticket, TicketType).filter(
            TicketType.admits == 'full',
            Ticket.paid == True,  # noqa
            Ticket.transfer_reminder_sent == False,
        ).group_by(User).having(func.count() > 1)

        for user in users_to_email:
            msg = Message("Your Electromagnetic Field Tickets",
                          sender=app.config['TICKETS_EMAIL'],
                          recipients=[user.email])

            msg.body = render_template("emails/transfer-reminder.txt", user=user)

            app.logger.info('Emailing %s transfer reminder', user.email)
            mail.send(msg)

            for ticket in user.tickets:
                ticket.transfer_reminder_sent = True
            db.session.commit()


class SendTickets(Command):

    def run(self):
        paid_items = Ticket.query.filter_by(paid=True).join(TicketType).filter(or_(
            TicketType.admits.in_(['full', 'kid', 'car', 'campervan']),
            TicketType.fixed_id.in_(range(14, 24))))

        users = (paid_items.filter(Ticket.emailed == False).join(User)  # noqa
                           .group_by(User).with_entities(User).order_by(User.id))

        for user in users:
            user_tickets = Ticket.query.filter_by(paid=True).join(TicketType, User).filter(
                TicketType.admits.in_(['full', 'kid', 'car', 'campervan']),
                User.id == user.id)

            plural = (user_tickets.count() != 1 and 's' or '')

            msg = Message("Your Electromagnetic Field Ticket%s" % plural,
                          sender=app.config['TICKETS_EMAIL'],
                          recipients=[user.email])

            msg.body = render_template("emails/receipt.txt", user=user)

            attach_tickets(msg, user)

            app.logger.info('Emailing %s receipt for %s tickets', user.email, user_tickets.count())
            mail.send(msg)

            db.session.commit()


class MakeAdmin(Command):
    """
    Make the first user in the DB an admin for testing purposes
    """
    option_list = (Option('-u', '--user-id', dest='user_id', help="The user_id to make an admin (defaults to first)"),)

    def run(self, user_id):
        if user_id:
            user = User.query.get(user_id)
        else:
            user = User.query.order_by(User.id).first()

        user.grant_permission('admin')
        db.session.commit()

        print('%r is now an admin' % user.name)

class CreatePermissions(Command):
    def run(self):
        for permission in ('admin', 'arrivals', 'cfp_reviewer', 'cfp_anonymiser', 'cfp_schedule'):
            if not Permission.query.filter_by(name=permission).first():
                db.session.add(Permission(permission))

        db.session.commit()

class MakeFakeUsers(Command):
    def run(self):
        if not User.query.filter_by(email='admin@test.invalid').first():
            user = User('admin@test.invalid', 'Test Admin')
            user.grant_permission('admin')
            cfp = TalkProposal()
            cfp.user = user
            cfp.title = 'test (admin)'
            cfp.description = 'test proposal from admin'
            db.session.add(user)

        if not User.query.filter_by(email='anonymiser@test.invalid').first():
            user2 = User('anonymiser@test.invalid', 'Test Anonymiser')
            user2.grant_permission('cfp_anonymiser')
            cfp = TalkProposal()
            cfp.user = user2
            cfp.title = 'test (anonymiser)'
            cfp.description = 'test proposal from anonymiser'
            db.session.add(user2)

        if not User.query.filter_by(email='reviewer@test.invalid').first():
            user3 = User('reviewer@test.invalid', 'Test Reviewer')
            user3.grant_permission('cfp_reviewer')
            cfp = TalkProposal()
            cfp.user = user3
            cfp.title = 'test (reviewer)'
            cfp.description = 'test proposal from reviewer'
            db.session.add(user3)

        if not User.query.filter_by(email='arrivals@test.invalid').first():
            user4 = User('arrivals@test.invalid', 'Test Arrivals')
            user4.grant_permission('arrivals')
            cfp = TalkProposal()
            cfp.user = user4
            cfp.title = 'test (arrivals)'
            cfp.description = 'test proposal from arrivals'
            db.session.add(user4)

        db.session.commit()


class MakeFakeTickets(Command):
    def run(self):
        faker = Faker()
        for i in range(1500):
            user = User('user_%s@test.invalid' % i, faker.name())
            db.session.add(user)
            db.session.commit()

        for user in User.query.all():
            try:
                # Choose a random number and type of tickets for this user
                full_count = random.choice([1] * 3 + [2, 3])
                full_type = TicketType.query.filter_by(fixed_id=random.choice([0, 1, 2, 3] * 30 + [9, 10] * 3 + [4])).one()
                full_tickets = [Ticket(user.id, type=full_type) for _ in range(full_count)]

                kids_count = random.choice([0] * 10 + [1, 2])
                kids_type = TicketType.query.filter_by(fixed_id=random.choice([5, 11, 6])).one()
                kids_tickets = [Ticket(user.id, type=kids_type) for _ in range(kids_count)]

                vehicle_count = random.choice([0] * 2 + [1])
                vehicle_type = TicketType.query.filter_by(fixed_id=random.choice([7] * 5 + [8])).one()
                vehicle_tickets = [Ticket(user.id, type=vehicle_type) for _ in range(vehicle_count)]

                for t in full_tickets + kids_tickets + vehicle_tickets:
                    t.paid = random.choice([True] * 4 + [False])
                    t.refunded = random.choice([False] * 20 + [True])

                db.session.commit()

            except TicketLimitException:
                db.session.rollback()


class ImportVenues(Command):
    venues = [
        ('Stage A', ['talk', 'performance'], 100),
        ('Stage B', ['talk'], 99),
        ('Stage C', ['talk'], 98),
        ('Workshop 1', ['workshop'], 97),
        ('Workshop 2', ['workshop'], 96),
    ]

    def run(self):
        for name, type, priority in self.venues:
            type_str = ','.join(type)
            if (Venue.query.filter_by(name=name, type=type_str).all()):
                continue

            venue = Venue()
            venue.name = name
            venue.type = type_str
            venue.priority = priority
            db.session.add(venue)
            app.logger.info('Adding venue "%s" as type "%s"' % (name, type))

        db.session.commit()

class SetRoughDurations(Command):
    def run(self):
        length_map = {
            '> 45 mins': 60,
            '25-45 mins': 30,
            '10-25 mins': 20,
            '< 10 mins': 10
        }

        proposals = Proposal.query.filter_by(scheduled_duration=None, type='talk').\
            filter(Proposal.state.in_(['accepted', 'finished'])).all()

        for proposal in proposals:
            proposal.scheduled_duration = length_map[proposal.length]
            app.logger.info('Setting duration for talk "%s" to "%s"' % (proposal.title, proposal.scheduled_duration))

        db.session.commit()

class OutputSchedulerData(Command):
    def run(self):
        proposals = Proposal.query.filter(Proposal.scheduled_duration.isnot(None)).\
            filter(Proposal.state.in_(['finished', 'accepted'])).\
            filter(Proposal.type.in_(['talk', 'workshop'])).all()

        proposal_data = []
        for proposal in proposals:
            export = {
                'id': proposal.id,
                'duration': proposal.scheduled_duration,
                'speakers': [ proposal.user.id ],
                'title': proposal.title,
                'valid_venues': [ v.id for v in proposal.get_allowed_venues() ],
                'time_ranges': [
                    {"start": str(p.start), "end": str(p.end)} for p in proposal.get_allowed_time_periods_with_default()
                ],
            }

            if proposal.scheduled_venue:
                export['venue'] = proposal.scheduled_venue
            if proposal.potential_venue:
                export['venue'] = proposal.potential_venue

            if proposal.scheduled_time:
                export['time'] = str(proposal.scheduled_time)
            if proposal.potential_time:
                export['time'] = str(proposal.potential_time)

            proposal_data.append(export)

        with open('schedule.json', 'w') as outfile:
            json.dump(proposal_data, outfile, sort_keys=True, indent=4, separators=(',', ': '))

        db.session.commit()

class ImportSchedulerData(Command):
    option_list = [
        Option('-f', '--file', dest='filename',
            help='The .json file to load',
            default='schedule.json'),
        Option('-p', '--persist', dest='persist', action='store_true',
            help='Persist the changes rather than doing a dry run')
    ]

    def run(self, filename, persist):
        schedule = json.load(open(filename))

        for event in schedule:
            if 'time' not in event or not event['time']:
                continue
            if 'venue' not in event or not event['venue']:
                continue

            proposal = Proposal.query.filter_by(id=event['id']).one()

            # Keep history of the venue while updating
            current_scheduled_venue = None
            previous_potential_venue = None
            if proposal.scheduled_venue:
                current_scheduled_venue = proposal.scheduled_venue
            if proposal.potential_venue:
                previous_potential_venue = proposal.potential_venue

            proposal.potential_venue = event['venue']
            if str(proposal.potential_venue) == str(current_scheduled_venue):
                proposal.potential_venue = None

            # Same for time
            previous_potential_time = proposal.potential_time
            proposal.potential_time = parser.parse(event['time'])
            if proposal.potential_time == proposal.scheduled_time:
                proposal.potential_time = None

            # Then say what changed
            if str(proposal.potential_venue) != str(previous_potential_venue) or proposal.potential_time != previous_potential_time:
                previous_venue_name = new_venue_name = None
                if previous_potential_venue:
                    previous_venue_name = Venue.query.filter_by(id=previous_potential_venue).one().name
                if proposal.potential_venue:
                    new_venue_name = Venue.query.filter_by(id=proposal.potential_venue).one().name

                # And we want to try and make sure both are populated
                if proposal.potential_venue and not proposal.potential_time:
                    proposal.potential_time = proposal.scheduled_time
                if proposal.potential_time and not proposal.potential_venue:
                    proposal.potential_venue = proposal.scheduled_venue
                app.logger.info('Moved "%s": "%s" on "%s" -> "%s" on "%s"' % (proposal.title, previous_venue_name, previous_potential_time, new_venue_name, proposal.potential_time))

        if persist:
            db.session.commit()
        else:
            app.logger.info("DRY RUN: `make importschedulerdata` to persist these")
            db.session.rollback()

class RunScheduler(Command):
    def run(self):
        sm = SlotMachine()
        sm.schedule(app.config['EVENT_START'], 'schedule.json', 'schedule.json')

class ApplyPotentialSchedule(Command):
    def run(self):
        proposals = Proposal.query.filter(
            (Proposal.potential_venue.isnot(None) | Proposal.potential_time.isnot(None))).\
            filter(Proposal.scheduled_duration.isnot(None)).\
            filter(Proposal.state.in_(['accepted', 'finished'])).\
            all()

        for proposal in proposals:
            user = proposal.user

            previously_unscheduled = True
            if proposal.scheduled_venue or proposal.scheduled_time:
                previously_unscheduled = False

            if proposal.potential_venue:
                proposal.scheduled_venue = proposal.potential_venue
                proposal.potential_venue = None

            if proposal.potential_time:
                proposal.scheduled_time = proposal.potential_time
                proposal.potential_time = None

            venue_name = Venue.query.filter_by(id=proposal.scheduled_venue).one().name

            if previously_unscheduled:
                msg = Message("Your EMF %s has been scheduled ('%s')" % (proposal.type, proposal.title),
                              sender=app.config['SPEAKERS_EMAIL'],
                              recipients=[user.email])

                msg.body = render_template("emails/cfp-slot-scheduled.txt", user=user, proposal=proposal, venue_name=venue_name)
                app.logger.info('Emailing %s about proposal %s being scheduled', user.email, proposal.title)
            else:
                msg = Message("Your EMF %s slot has been moved ('%s')" % (proposal.type, proposal.title),
                              sender=app.config['SPEAKERS_EMAIL'],
                              recipients=[user.email])

                msg.body = render_template("emails/cfp-slot-moved.txt", user=user, proposal=proposal, venue_name=venue_name)
                app.logger.info('Emailing %s about proposal %s moving', user.email, proposal.title)

            mail.send(msg)
            db.session.commit()

class SendEmails(Command):
    def run(self):
        with mail.connect() as conn:
            for rec in EmailJobRecipient.query.filter(EmailJobRecipient.sent == False):  # noqa
                self.send_email(conn, rec)

    def send_email(self, conn, rec):
        msg = Message(rec.job.subject, sender=app.config['CONTACT_EMAIL'])
        msg.add_recipient(rec.user.email)
        msg.body = rec.job.text_body
        msg.html = rec.job.html_body
        conn.send(msg)
        rec.sent = True
        db.session.add(rec)
        db.session.commit()


class CreateCalendars(Command):
    def run(self):
        icals = json.load(open('calendars.json'))

        for cal in icals:
            existing_calendar = CalendarSource.query.filter_by(url=cal['url']).first()
            if existing_calendar:
                source = existing_calendar
                app.logger.info('Refreshing calendar %s', source.name)
            else:
                source = CalendarSource(cal['url'])
                app.logger.info('Adding calendar %s', cal['name'])

            cal['lat'] = cal.get('lat')
            cal['lon'] = cal.get('lon')

            for f in ['name', 'type', 'priority', 'main_venue', 'lat', 'lon']:
                cur_val = getattr(source, f)
                new_val = cal[f]

                if cur_val != new_val:
                    app.logger.info(' %10s: %r -> %r', f, cur_val, new_val)
                    setattr(source, f, new_val)

            db.session.add(source)

        db.session.commit()

class RefreshCalendars(Command):
    def run(self):
        for source in CalendarSource.query.filter_by(enabled=True).all():
            source.refresh()

        db.session.commit()

class ExportCalendars(Command):
    def run(self):
        data = []
        calendars = CalendarSource.query.filter_by(enabled=True) \
                                  .order_by(CalendarSource.priority, CalendarSource.id)
        for source in calendars:
            source_data = OrderedDict([
                ('name', source.name),
                ('url', source.url),
                ('type', source.type),
                ('priority', source.priority),
                ('main_venue', source.main_venue)])
            if source.lat:
                source_data['lat'] = source.lat
                source_data['lon'] = source.lon

            data.append(source_data)

        json.dump(data, open('calendars.json', 'w'), indent=4, separators=(',', ': '))


class CreateParkingTickets(Command):
    def run(self):
        tt = TicketType.query.filter_by(fixed_id=24).one()

        for i in range(1, 50 + 1):
            email = 'user_%s@parking.invalid' % i
            if not User.query.filter_by(email=email).first():
                u = User(email, 'Parking ticket %s' % i)
                db.session.add(u)
                db.session.commit()

                t = Ticket(u.id, tt)
                t.paid = True
                t.emailed = True

        db.session.commit()


if __name__ == "__main__":
    manager = Manager(create_app())
    manager.add_command('createdb', CreateDB())
    manager.add_command('db', MigrateCommand)

    manager.add_command('createbankaccounts', CreateBankAccounts())
    manager.add_command('loadofx', LoadOfx())
    manager.add_command('reconcile', Reconcile())

    manager.add_command('sendtransferreminder', SendTransferReminder())
    manager.add_command('createtickets', CreateTickets())
    manager.add_command('sendtickets', SendTickets())

    manager.add_command('lockproposals', LockProposals())
    manager.add_command('importcfp', ImportCFP())

    manager.add_command('createperms', CreatePermissions())
    manager.add_command('makeadmin', MakeAdmin())
    manager.add_command('makefakeusers', MakeFakeUsers())
    manager.add_command('makefaketickets', MakeFakeTickets())

    manager.add_command('sendemails', SendEmails())

    manager.add_command('emailspeakersaboutslot', EmailSpeakersAboutSlot())
    manager.add_command('emailspeakersaboutfinalising', EmailSpeakersAboutFinalising())
    manager.add_command('rejectunacceptedtalks', RejectUnacceptedTalks())

    manager.add_command('importvenues', ImportVenues())
    manager.add_command('setroughdurations', SetRoughDurations())
    manager.add_command('outputschedulerdata', OutputSchedulerData())
    manager.add_command('importschedulerdata', ImportSchedulerData())
    manager.add_command('runscheduler', RunScheduler())
    manager.add_command('applypotentialschedule', ApplyPotentialSchedule())

    manager.add_command('createcalendars', CreateCalendars())
    manager.add_command('refreshcalendars', RefreshCalendars())
    manager.add_command('exportcalendars', ExportCalendars())

    manager.add_command('createparkingtickets', CreateParkingTickets())
    manager.run()
