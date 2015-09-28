#!/usr/bin/env python
# coding=utf-8

import ofxparse
from flask.ext.script import Command, Manager, Option
from flask import render_template
from flask_mail import Message
from sqlalchemy.orm.exc import NoResultFound

from datetime import datetime, timedelta

from main import app, mail, db
from models import (
    User, TicketType, Ticket, TicketPrice
)
from models.payment import (
    BankAccount, BankTransaction,
)
from views.tickets import render_receipt, render_pdf

manager = Manager(app)

class CreateDB(Command):
    def run(self):
        from main import db
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
            # date is actually dtposted and is a datetime
            if txn.date < datetime(2014, 1, 1):
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

            if txn.payee.startswith("GOCARDLESS "):
                app.logger.info('Suppressing GoCardless transfer %s', txn.id)
                if doit:
                    txn.suppressed = True
                    db.session.commit()
                continue

            if txn.payee.startswith("STRIPE PAYMENTS EU "):
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

                msg = Message("Electromagnetic Field ticket purchase update",
                              sender=app.config['TICKETS_EMAIL'],
                              recipients=[payment.user.email])
                msg.body = render_template("emails/tickets-paid-email-banktransfer.txt",
                              user=payment.user, payment=payment)
                mail.send(msg)

            app.logger.info("Payment reconciled")
            paid += 1

        app.logger.info('Reconciliation complete: %s paid, %s failed', paid, failed)

def add_ticket_types(ticket_list):
    types = []

    for row in ticket_list:
        tt = TicketType(*row[:5], personal_limit=row[5], description=row[9],
            has_badge=row[8], discount_token=row[10], expires=row[11])
        tt.prices = [TicketPrice('GBP', row[6]), TicketPrice('EUR', row[7])]
        types.append(tt)

    for tt in types:
        existing_tt = TicketType.query.get(tt.id)
        if existing_tt:
            app.logger.info('Refreshing TicketType %s (id: %s)', tt.name, tt.id)
            for f in ['name', 'type_limit', 'expires', 'personal_limit', 'order', 'description']:
                cur_val = getattr(existing_tt, f)
                new_val = getattr(tt, f)

                if cur_val != new_val:
                     app.logger.info(' %10s: %r -> %r', f, cur_val, new_val)
                     setattr(existing_tt, f, new_val)
        else:
            app.logger.info('Adding TicketType %s (id: %s)', tt.name, tt.id)
            db.session.add(tt)

        db.session.commit()

    app.logger.info('Tickets refreshed')

class CreateTickets(Command):
    def run(self):
        #
        # if you change these, change ticket_forms in views/tickets.py as well.
        #

        type_data = [
            # (id, order, admits, name, type limit, personal limit, GBP, EUR, Description)
            # Leave order 0 & 1 free for discount tickets
            (0, 2, 'full', 'Earlybird Ticket', 100, 10, 90.00, 115.00, True, None),
            (1, 3, 'full', 'Full Camp Ticket', 100, 10, 95.00, 120.00, True, None),
            (2, 5, 'full', 'Full Camp Ticket', 1100, 10, 105.00, 135.00, True, None),
            (3, 8, 'full', 'Full Camp Ticket (Supporter)', 1100, 10, 125.00, 160.00, True,
                "Support this non-profit event by paying a little more. "
                "All money will go towards making EMF more awesome."),

            (4, 8, 'full', 'Full Camp Ticket (Supporter)', 0, 10, 150.00, 190.00, True,
                "Support this non-profit event by paying a little more. "
                "All money will go towards making EMF more awesome."),

            (5, 10, 'kid', 'Under-16 Camp Ticket', 500, 10, 40.00, 50.00, True,
                "For visitors born after August 28th, 1998. "
                "All under-16s  must be accompanied by an adult."),

            (6, 15, 'kid', 'Under-5 Camp Ticket', 200, 4, 0, 0, False,
                "For children born after August 28th, 2009. "
                "All children must be accompanied by an adult."),

            (7, 30, 'car', 'Parking Ticket', 400, 4, 15.00, 20.00, False,
                "We're trying to keep cars on-site to a minimum. "
                "Please take public transport or find someone to share with if possible."),

            (8, 35, 'campervan',
                'Caravan/Campervan Ticket', 50, 2, 30.00, 40.00, False,
                "If you bring a caravan, you won't need a separate parking ticket for the towing car."),
        ]
        # none of these tickets have tokens or expiry dates
        type_data = [ t + (None, None) for t in type_data]

        add_ticket_types(type_data)


class CreateTicketTokens(Command):
    # This is effectively the same as creating a ticket
    def run(self):
        discount_ticket_types = [
            (9, 0, 'full', 'Complimentary Full Camp Ticket', 1, 1, 0.0, 0.0, True, None, 'super-lucky'),
            (10, 1, 'full', 'Discount Full Camp Ticket', 10, 1, 70.00, 90.00, True, None, 'lucky')
        ]

        discount_ticket_types = [ tt + (datetime.utcnow() + timedelta(days=7), )
            for tt in discount_ticket_types]

        add_ticket_types(discount_ticket_types)


class MakeAdmin(Command):
    """
      Make userid one an admin for testing purposes.
    """
    option_list = (Option('-u', '--userid', dest='userid', help="The userid to make an admin (defaults to 1)"),)

    def run(self, userid):
        if not userid:
            userid = 1
        user = User.query.get(userid)
        user.admin = True
        s = db.object_session(user)
        s.commit()

        print '%s is now an admin' % (user.name)

class MakeArrivals(Command):
    """
      Make userid one an arrivals operator for testing purposes.
    """
    option_list = (Option('-u', '--userid', dest='userid', help="The userid to make an arrivals operator (defaults to 1)"),)

    def run(self, userid):
        if not userid:
            userid = 1
        user = User.query.get(userid)
        user.arrivals = True
        s = db.object_session(user)
        s.commit()

        print '%s is now an arrivals operator' % (user.name)


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

            msg.body = render_template("receipt.txt", user=user)
            msg.attach('Receipt.pdf', 'application/pdf', pdf.read())

            app.logger.info('Emailing %s receipt for %s tickets', user.email, tickets.count())
            mail.send(msg)

            for ticket in tickets:
                ticket.emailed = True
            db.session.commit()

if __name__ == "__main__":
    manager.add_command('createdb', CreateDB())
    manager.add_command('createbankaccounts', CreateBankAccounts())
    manager.add_command('loadofx', LoadOfx())
    manager.add_command('reconcile', Reconcile())
    manager.add_command('createtickets', CreateTickets())
    manager.add_command('makeadmin', MakeAdmin())
    manager.add_command('makearrivals', MakeArrivals())
    manager.add_command('createtokens', CreateTicketTokens())
    manager.add_command('sendtickets', SendTickets())
    manager.run()
