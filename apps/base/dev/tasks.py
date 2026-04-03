"""Development CLI tasks"""

import click
from flask import current_app as app
from sqlalchemy.exc import MultipleResultsFound, NoResultFound

from apps.cfp.schedule_tasks import create_venues
from apps.cfp.tasks import create_tags
from apps.tickets.tasks import create_product_groups
from apps.volunteer.init_data import shifts as init_shifts
from main import db
from models.feature_flag import FeatureFlag, refresh_flags
from models.payment import BankAccount
from models.site_state import refresh_states
from models.user import User

from . import dev_cli
from .fake import FakeDataGenerator


@dev_cli.command("data")
@click.pass_context
@click.option("--idempotent", is_flag=True)
def dev_data(ctx, idempotent):
    """Make all categories of fake data for dev"""
    ctx.invoke(enable_cfp)
    ctx.invoke(volunteer_data)
    ctx.invoke(create_tags)
    ctx.invoke(create_venues)
    ctx.invoke(create_bank_accounts)
    ctx.invoke(create_product_groups)
    # fake_data always generates 120 users and a bunch of other stuff
    # so don't automatically run it every time the container starts up
    ctx.invoke(fake_data, idempotent=idempotent)


@dev_cli.command("cfp_data")
@click.option("--idempotent", is_flag=True)
def fake_data(idempotent=False):
    """Make fake users, proposals, locations, etc"""
    if idempotent:
        # As a shortcut, just assume if we've created users already then we
        # don't need to do anything again.  This does mean we'll miss out
        # if someone adds new functionality here until the database is
        # emptied.
        if db.session.query(User).count() > 120:
            return

    fdg = FakeDataGenerator()
    fdg.run()


@dev_cli.command("enable_cfp")
def enable_cfp():
    for flag in ["LINE_UP", "CFP"]:
        if not FeatureFlag.query.get(flag):
            db.session.add(FeatureFlag(feature=flag, enabled=True))

    db.session.commit()
    db.session.flush()
    refresh_flags()
    refresh_states()


@dev_cli.command("volunteer_data")
def volunteer_data():
    """Make fake volunteer system data"""
    init_shifts()


@dev_cli.command("createbankaccounts")
def create_bank_accounts_cmd():
    create_bank_accounts()


def create_bank_accounts():
    """Create bank accounts if they don't exist"""
    gbp = BankAccount(
        sort_code="102030",
        acct_id="40506070",
        currency="GBP",
        active=True,
        payee_name="EMF Festivals Ltd",
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
        payee_name="EMF Festivals Ltd",
        institution="London Bank",
        address="13 Bartlett Place, London, WC1B 4NM",
        iban="GB33BUKB20201555555555",
        swift="BUKBGB33",
    )
    for acct in [gbp, eur]:
        try:
            BankAccount.query.filter_by(acct_id=acct.acct_id, sort_code=acct.sort_code).one()
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
