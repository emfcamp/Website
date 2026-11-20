import click

from apps.base import base
from apps.payments.banktransfer import reconcile_txns
from main import db
from models.payment import BankTransaction


@base.cli.command("reconcile")
@click.option("-d", "--doit", is_flag=True, help="set this to actually change the db")
def reconcile(doit):
    outstanding_txns = BankTransaction.query.filter_by(payment_id=None, suppressed=False)
    reconcile_txns(outstanding_txns, doit)
