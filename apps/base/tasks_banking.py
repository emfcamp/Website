from datetime import datetime, timedelta

import click
from flask import current_app as app

from apps.base import base
from apps.payments.banktransfer import reconcile_txns
from apps.payments.wise import (
    sync_wise_statement,
    wise_business_profile,
    wise_retrieve_accounts,
)
from main import db, wise
from models.payment import BankAccount, BankTransaction


@base.cli.command("sync_wisetransfer")
@click.argument("profile_id", type=click.INT, required=False)
def sync_wisetransfer(profile_id):
    """Sync transactions from all accounts associated with a Wise profile"""
    if profile_id is None:
        profile_id = wise_business_profile()

    accounts = wise_retrieve_accounts(profile_id)
    for account in accounts:
        # Each sync is performed in a separate transaction
        sync_wise_statement(profile_id, account.wise_balance_id, account.currency)


@base.cli.command("check_wisetransfer_ids")
@click.argument("profile_id", type=click.INT, required=False)
def check_wisetransfer_ids(profile_id):
    """Store referenceNumbers or check them if already stored"""
    if profile_id is None:
        profile_id = wise_business_profile()

    accounts = wise_retrieve_accounts(profile_id)
    for account in accounts:
        interval_end = datetime.utcnow()
        interval_start = interval_end - timedelta(days=120)
        statement = wise.balance_statements.statement(
            profile_id,
            account.wise_balance_id,
            account.currency,
            interval_start.isoformat() + "Z",
            interval_end.isoformat() + "Z",
        )

        bank_account = (
            BankAccount.query.with_for_update()
            .filter_by(
                wise_balance_id=account.wise_balance_id,
                currency=account.currency,
            )
            .one()
        )
        if not bank_account.active:
            app.logger.info(
                f"BankAccount for Wise balance account {account.wise_balance_id} and {account.currency} is not active, not checking"
            )
            db.session.commit()
            continue

        for transaction in statement.transactions:
            if transaction.type != "CREDIT":
                continue

            if transaction.details.type != "DEPOSIT":
                continue

            txns = BankTransaction.query.filter_by(
                account_id=bank_account.id,
                posted=transaction.date,
                type=transaction.details.type.lower(),
                payee=transaction.details.paymentReference,
            ).all()
            if len(txns) == 0:
                app.logger.error(f"Could not find transaction (did you run sync first?): {transaction}")
                continue
            if len(txns) > 1:
                app.logger.error(f"Found matching {len(txns)} matching transactions for: {transaction}")
                continue

            txn = txns[0]
            if txn.wise_id is None:
                txn.wise_id = transaction.referenceNumber
                continue
            if txn.wise_id != transaction.referenceNumber:
                app.logger.error(f"referenceNumber has changed from {txn.wise_id}: {transaction}")
                continue

        db.session.commit()


@base.cli.command("reconcile")
@click.option("-d", "--doit", is_flag=True, help="set this to actually change the db")
def reconcile(doit):
    outstanding_txns = BankTransaction.query.filter_by(payment_id=None, suppressed=False)
    reconcile_txns(outstanding_txns, doit)
