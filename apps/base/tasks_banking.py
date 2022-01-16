import click
import ofxparse
from datetime import datetime, timedelta

from flask import current_app as app
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from main import db, wise
from apps.base import base
from apps.payments.banktransfer import reconcile_txns
from apps.payments.wise import (
    wise_retrieve_accounts,
    wise_business_profile,
    sync_wise_statement,
)
from models.payment import BankAccount, BankTransaction


@base.cli.command("createbankaccounts")
def create_bank_accounts_cmd():
    create_bank_accounts()


def create_bank_accounts():
    """Create bank accounts if they don't exist"""
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
        except MultipleResultsFound:
            pass

    db.session.commit()


@base.cli.command("loadofx")
@click.argument("ofx_file", type=click.File("r"))
def load_ofx(ofx_file):
    """Import an OFX bank statement file"""
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


@base.cli.command("sync_wisetransfer")
@click.argument("profile_id", type=click.INT, required=False)
def sync_wisetransfer(profile_id):
    """Sync transactions from all accounts associated with a Wise profile"""
    if profile_id is None:
        profile_id = wise_business_profile()

    tw_accounts = wise_retrieve_accounts(profile_id)
    for tw_account in tw_accounts:
        # Each sync is performed in a separate transaction
        sync_wise_statement(
            profile_id, tw_account.borderless_account_id, tw_account.currency
        )


@base.cli.command("check_wisetransfer_ids")
@click.argument("profile_id", type=click.INT, required=False)
def check_wisetransfer_ids(profile_id):
    """Store referenceNumbers or check them if already stored"""
    if profile_id is None:
        profile_id = wise_business_profile()

    tw_accounts = wise_retrieve_accounts(profile_id)
    for tw_account in tw_accounts:
        interval_end = datetime.utcnow()
        interval_start = interval_end - timedelta(days=120)
        statement = wise.borderless_accounts.statement(
            profile_id,
            tw_account.borderless_account_id,
            tw_account.currency,
            interval_start.isoformat() + "Z",
            interval_end.isoformat() + "Z",
        )

        bank_account = (
            BankAccount.query.with_for_update()
            .filter_by(
                borderless_account_id=tw_account.borderless_account_id,
                currency=tw_account.currency,
            )
            .one()
        )
        if not bank_account.active:
            app.logger.info(
                f"BankAccount for borderless account {tw_account.borderless_account_id} and {tw_account.currency} is not active, not checking"
            )
            db.session.commit()
            continue

        for transaction in statement.transactions:
            if transaction.type != "CREDIT":
                continue

            txns = BankTransaction.query.filter_by(
                account_id=bank_account.id,
                posted=transaction.date,
                type=transaction.details.type.lower(),
                payee=transaction.details.paymentReference,
            ).all()
            if len(txns) == 0:
                app.logger.error(
                    f"Could not find transaction (did you run sync first?): {transaction}"
                )
                continue
            if len(txns) > 1:
                app.logger.error(
                    f"Found matching {len(txns)} matching transactions for: {transaction}"
                )
                continue

            txn = txns[0]
            if txn.wise_id is None:
                txn.wise_id = transaction.referenceNumber
                continue
            if txn.wise_id != transaction.referenceNumber:
                app.logger.error(
                    f"referenceNumber has changed from {txn.wise_id}: {transaction}"
                )
                continue

        db.session.commit()


@base.cli.command("reconcile")
@click.option("-d", "--doit", is_flag=True, help="set this to actually change the db")
def reconcile(doit):
    outstanding_txns = BankTransaction.query.filter_by(
        payment_id=None, suppressed=False
    )
    reconcile_txns(outstanding_txns, doit)
