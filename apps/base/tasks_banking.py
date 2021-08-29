import click
import ofxparse
from datetime import datetime

from flask import current_app as app
from sqlalchemy.orm.exc import NoResultFound

from main import db
from apps.base import base
from apps.payments import banktransfer
from models.payment import BankAccount, BankTransaction


@base.cli.command("createbankaccounts")
def create_bank_accounts_cmd():
    create_bank_accounts()


def create_bank_accounts():
    """ Create bank accounts if they don't exist """
    gbp = BankAccount(
        sort_code="102030",
        acct_id="40506070",
        currency="GBP",
        active=True,
        institution="London Bank",
        address="13 Bartlett Place, London, WC1B 4NM",
        iban=None,
        swift=None,
    )
    eur = BankAccount(
        sort_code=None,
        acct_id=None,
        currency="EUR",
        active=True,
        institution="London Bank",
        address="13 Bartlett Place, London, WC1B 4NM",
        iban="GB47LOND11213141516171",
        swift="GB47LOND",
    )
    for acct in [gbp, eur]:
        try:
            BankAccount.query.filter_by(
                acct_id=acct.acct_id, sort_code=acct.sort_code
            ).one()
        except NoResultFound:
            app.logger.info(
                "Adding %s account %s %s",
                acct.currency,
                acct.sort_code or acct.swift,
                acct.acct_id or acct.iban,
            )
            db.session.add(acct)

    db.session.commit()


@base.cli.command("loadofx")
@click.argument("ofx_file", type=click.File("r"))
def load_ofx(ofx_file):
    """ Import an OFX bank statement file """
    ofx = ofxparse.OfxParser.parse(ofx_file)

    acct_id = ofx.account.account_id
    sort_code = ofx.account.routing_number
    account = BankAccount.get(sort_code, acct_id)
    if ofx.account.statement.currency.lower() != account.currency.lower():
        app.logger.error(
            "Currency %s doesn't match account currency %s",
            ofx.account.statement.currency,
            account.currency,
        )
        return

    added = 0
    duplicate = 0
    dubious = 0

    for txn in ofx.account.statement.transactions:
        if 0 < int(txn.id) < 200101010000000:
            app.logger.debug("Ignoring uncleared transaction %s", txn.id)
            continue
        # date is actually dtposted and is a datetime
        if txn.date < datetime(2015, 1, 1):
            app.logger.debug("Ignoring historic transaction from %s", txn.date)
            continue
        if txn.amount <= 0:
            app.logger.info("Ignoring non-credit transaction for %s", txn.amount)
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
        if dbtxn.fit_id == "00000000":
            # There seems to be a serial in the payee field. Assume that's enough for uniqueness.
            if matches.count():
                app.logger.debug("Ignoring duplicate transaction from %s", dbtxn.payee)
                duplicate += 1

            else:
                db.session.add(dbtxn)
                added += 1

        else:
            different_fit_ids = matches.filter(BankTransaction.fit_id != dbtxn.fit_id)
            same_fit_ids = matches.filter(BankTransaction.fit_id == dbtxn.fit_id)

            if same_fit_ids.count():
                app.logger.debug("Ignoring duplicate transaction %s", dbtxn.fit_id)
                duplicate += 1

            elif BankTransaction.query.filter(
                BankTransaction.fit_id == dbtxn.fit_id
            ).count():
                app.logger.error(
                    "Non-matching transactions with same fit_id %s", dbtxn.fit_id
                )
                dubious += 1

            elif different_fit_ids.count():
                app.logger.warn(
                    "%s matching transactions with different fit_ids for %s",
                    different_fit_ids.count(),
                    dbtxn.fit_id,
                )
                # fit_id may have been changed, so add it anyway
                db.session.add(dbtxn)
                added += 1
                dubious += 1

            else:
                db.session.add(dbtxn)
                added += 1

    db.session.commit()
    app.logger.info(
        "Import complete: %s new, %s duplicate, %s dubious", added, duplicate, dubious
    )


@base.cli.command("reconcile")
@click.option("-d", "--doit", is_flag=True, help="set this to actually change the db")
def reconcile(doit):
    txns = BankTransaction.query.filter_by(payment_id=None, suppressed=False)

    paid = 0
    failed = 0

    for txn in txns:
        if txn.type.lower() not in ("other", "directdep"):
            raise ValueError("Unexpected transaction type for %s: %s", txn.id, txn.type)

        if txn.payee.startswith("GOCARDLESS ") or txn.payee.startswith("GC C1 EMF"):
            app.logger.info("Suppressing GoCardless transfer %s", txn.id)
            if doit:
                txn.suppressed = True
                db.session.commit()
            continue

        if txn.payee.startswith("STRIPE PAYMENTS EU ") or txn.payee.startswith(
            "STRIPE STRIPE"
        ):
            app.logger.info("Suppressing Stripe transfer %s", txn.id)
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

        app.logger.info(
            "Matched to payment %s by %s for %s %s",
            payment.id,
            payment.user.name,
            payment.amount,
            payment.currency,
        )

        if doit:
            payment.lock()

        if txn.amount != payment.amount:
            app.logger.warn(
                "Transaction amount %s doesn't match %s, skipping",
                txn.amount,
                payment.amount,
            )
            failed += 1
            db.session.rollback()
            continue

        if txn.account.currency != payment.currency:
            app.logger.warn(
                "Transaction currency %s doesn't match %s, skipping",
                txn.account.currency,
                payment.currency,
            )
            failed += 1
            db.session.rollback()
            continue

        if payment.state == "paid":
            app.logger.error("Payment %s has already been paid", payment.id)
            failed += 1
            db.session.rollback()
            continue

        if doit:
            txn.payment = payment
            payment.paid()

            banktransfer.send_confirmation(payment)

            db.session.commit()

        app.logger.info("Payment reconciled")
        paid += 1

    app.logger.info("Reconciliation complete: %s paid, %s failed", paid, failed)
