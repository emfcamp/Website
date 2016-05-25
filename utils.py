#!/usr/bin/env python
# coding=utf-8
from datetime import datetime, timedelta

import ofxparse
from flask.ext.script import Command, Manager, Option
from flask.ext.migrate import MigrateCommand
from flask import render_template, current_app as app
from flask_mail import Message
from sqlalchemy.orm.exc import NoResultFound
from main import create_app, mail, db
from models import (
    User, TicketType, Ticket, TicketPrice
)
from models.payment import (
    BankAccount, BankTransaction,
)
from models.cfp import Proposal, TalkProposal, WorkshopProposal, InstallationProposal
from models.permission import Permission
from apps.tickets import render_receipt, render_pdf
from apps.payments import banktransfer
from unicodecsv import DictReader


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
        ofx = ofxparse.OfxParser.parse(file(filename))

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
        (2, 4, 'full', 'Full Camp Ticket', 500, 10, 120.00, 158.00, True, None, None, datetime(2016, 4, 4, 11, 0), True),
        # (3, 5, 'full', 'Full Camp Ticket', 400, 10, 120.00, 165.00, True, None, None, None, None),
        (3, 8, 'full', 'Full Camp Ticket (Supporter)', 56, 10, 130.00, 180.00, True,
            "Support this non-profit event by paying a bit more. "
            "All money will go towards making EMF more awesome.",
            None, None, True),
        (9, 8, 'full', 'Full Camp Ticket (Supporter)', 1100, 10, 130.00, 170.00, True,
            "Support this non-profit event by paying a bit more. "
            "All money will go towards making EMF more awesome.",
            None, None, True),

        (4, 9, 'full', 'Full Camp Ticket (Gold Supporter)', 6, 10, 150.00, 210.00, True,
            "Pay even more, receive our undying gratitude.",
            None, None, True),
        (10, 9, 'full', 'Full Camp Ticket (Gold Supporter)', 1100, 10, 150.00, 195.00, True,
            "Pay even more, receive our undying gratitude.",
            None, None, True),

        (5, 10, 'kid', 'Under-16 Camp Ticket', 11, 10, 45.00, 64.00, True,
            "For visitors born after August 5th, 2000. "
            "All under-16s must be accompanied by an adult.",
            None, None, True),
        (11, 10, 'kid', 'Under-16 Camp Ticket', 500, 10, 45.00, 60.00, True,
            "For visitors born after August 5th, 2000. "
            "All under-16s must be accompanied by an adult.",
            None, None, True),

        (6, 15, 'kid', 'Under-5 Camp Ticket', 200, 4, 0, 0, False,
            "For children born after August 5th, 2011. "
            "All children must be accompanied by an adult.",
            None, None, True),

        (13, 25, 'other',
            'Tent (Template)', 0, 1, 300.00, 400.00, False,
            "Pre-ordered village tents will be placed on site before the event starts.",
            None, None, True),

        (7, 30, 'car', 'Parking Ticket', 450, 4, 15.00, 21.00, False,
            "We're trying to keep cars to a minimum. "
            "Please take public transport or car-share if you can.",
            None, None, True),

        (8, 35, 'campervan',
            'Caravan/Campervan Ticket', 60, 2, 30.00, 42.00, False,
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


class SendTickets(Command):

    def run(self):
        all_tickets = Ticket.query.filter_by(paid=True, emailed=False)
        users = all_tickets.join(User).group_by(User).with_entities(User).order_by(User.id)

        for user in users:
            tickets = all_tickets.filter_by(user_id=user.id)
            page = render_receipt(tickets, pdf=True)
            pdf = render_pdf(page, url_root=app.config.get('BASE_URL'))
            plural = (tickets.count() != 1 and 's' or '')

            msg = Message("Your Electromagnetic Field Ticket%s" % plural,
                          sender=app.config['TICKETS_EMAIL'],
                          recipients=[user.email])

            msg.body = render_template("emails/receipt.txt", user=user)
            msg.attach('Receipt.pdf', 'application/pdf', pdf.read())

            app.logger.info('Emailing %s receipt for %s tickets', user.email, tickets.count())
            mail.send(msg)

            for ticket in tickets:
                ticket.emailed = True
            db.session.commit()


class LockProposals(Command):

    def run(self):
        edit_window = timedelta(days=app.config.get('EDIT_WINDOW', 2))
        app.logger.info('Locking proposals older than %s', edit_window)
        new_proposals = Proposal.query.filter_by(state='new').all()
        lock_count = 0
        for proposal in new_proposals:
            deadline = proposal.created + edit_window

            if datetime.utcnow() > deadline:
                proposal.set_state('locked')

                app.logger.debug('Locking proposal %s', proposal.id)
                db.session.commit()
                lock_count += 1

        app.logger.info('Locked %s proposals', lock_count)


class ImportCFP(Command):
    option_list = [Option('-f', '--file', dest='filename',
                          help='The .csv file to load',
                          default='tests/2014_proposals.csv'),
                   Option('-s', '--state', dest='state', default='locked',
                          help='The state to import the proposals as')]

    def run(self, filename, state):
        with open(filename) as csvfile:
            # id, title, description, length, need_finance,
            # one_day, type, experience, attendees, size
            reader = DictReader(csvfile)
            count = 0
            for row in reader:
                if Proposal.query.filter_by(title=row['title']).first():
                    continue

                user = User('user_%s@test.invalid' % count, 'test_cfp_user_%s' % count)
                db.session.add(user)

                proposal = TalkProposal() if row['type'] == u'talk' else\
                    WorkshopProposal() if row['type'] == u'workshop' else\
                    InstallationProposal()

                proposal.state = state
                proposal.title = row['title']
                proposal.description = row['description']

                proposal.one_day = True if row.get('one_day') == 't' else False
                proposal.needs_money = True if row.get('need_finance') == 't' else False

                if row['type'] == 'talk':
                    proposal.length = row['length']

                elif row['type'] == 'workshop':
                    proposal.length = row['length']
                    proposal.attendees = row['attendees']

                else:
                    proposal.size = row['size']

                proposal.user = user
                db.session.add(proposal)
                db.session.commit()
                count += 1
        app.logger.info('Imported %s proposals' % count)


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

        print '%r is now an admin' % user.name

class CreatePermissions(Command):
    def run(self):
        for permission in ('admin', 'arrivals', 'cfp_reviewer', 'cfp_anonymiser'):
            if not Permission.query.filter_by(name=permission).first():
                db.session.add(Permission(permission))

        db.session.commit()

class MakeUsers(Command):
    def run(self):
        user = User('admin@test.invalid', 'Test Admin')
        user.grant_permission('admin')
        cfp = TalkProposal()
        cfp.user = user
        cfp.title = 'test (admin)'
        cfp.description = 'test proposal from admin'

        user2 = User('anonymiser@test.invalid', 'Test Anonymiser')
        user2.grant_permission('cfp_anonymiser')
        cfp = TalkProposal()
        cfp.user = user2
        cfp.title = 'test (anonymiser)'
        cfp.description = 'test proposal from anonymiser'

        user3 = User('reviewer@test.invalid', 'Test Reviewer')
        user3.grant_permission('cfp_reviewer')
        cfp = TalkProposal()
        cfp.user = user3
        cfp.title = 'test (reviewer)'
        cfp.description = 'test proposal from reviewer'

        user4 = User('arrivals@test.invalid', 'Test Arrivals')
        user4.grant_permission('arrivals')
        cfp = TalkProposal()
        cfp.user = user4
        cfp.title = 'test (arrivals)'
        cfp.description = 'test proposal from arrivals'

        db.session.commit()


if __name__ == "__main__":
    manager = Manager(create_app())
    manager.add_command('createdb', CreateDB())
    manager.add_command('db', MigrateCommand)

    manager.add_command('createbankaccounts', CreateBankAccounts())
    manager.add_command('loadofx', LoadOfx())
    manager.add_command('reconcile', Reconcile())

    manager.add_command('createtickets', CreateTickets())
    manager.add_command('sendtickets', SendTickets())

    manager.add_command('lockproposals', LockProposals())
    manager.add_command('importcfp', ImportCFP())

    manager.add_command('createperms', CreatePermissions())
    manager.add_command('makeadmin', MakeAdmin())
    manager.add_command('makeusers', MakeUsers())

    manager.run()
