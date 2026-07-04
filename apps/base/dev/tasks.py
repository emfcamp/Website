"""Development CLI tasks"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from itertools import islice

import click
from flask import current_app as app
from sqlalchemy.exc import MultipleResultsFound, NoResultFound

from apps.cfp.tasks import create_tags
from apps.common.walletpass import generate_pkpass, generate_unsigned_pkpass
from apps.tickets.tasks import create_product_groups
from apps.volunteer.init_data import shifts as init_shifts
from main import db
from models.content import Venue
from models.content.schedule import ScheduleItemType
from models.content.venue import TimeBlock
from models.feature_flag import FeatureFlag, refresh_flags
from models.payment import BankAccount
from models.site_state import SiteState, refresh_states
from models.user import User

from ...config import config
from . import dev_cli
from .fake import FakeDataGenerator


@dev_cli.command("data")
@click.pass_context
@click.option("--idempotent", is_flag=True)
def dev_data(ctx, idempotent):
    """Make all categories of fake data for dev"""

    # If the site state hasn't been set, set it to sales.
    res = db.session.query(SiteState).filter_by(name="site_state").one_or_none()
    if not res:
        db.session.add(SiteState(name="site_state", state="sales"))
        db.session.commit()

    ctx.invoke(enable_cfp)
    ctx.invoke(volunteer_data)
    ctx.invoke(create_tags)
    ctx.invoke(create_venues)
    ctx.invoke(create_bank_accounts)
    ctx.invoke(create_product_groups)
    # fake_data always generates 120 users and a bunch of other stuff
    # so don't automatically run it every time the container starts up
    ctx.invoke(fake_data, idempotent=idempotent)


@dataclass
class VenueDefinition:
    name: str
    priority: int
    latlon: tuple[float, float]
    allows_attendee_content: bool
    timeblocks: dict[ScheduleItemType, tuple[time, time]]
    capacity: int | None

    @property
    def location(self) -> str:
        return f"POINT({self.latlon[1]} {self.latlon[0]})"

    def as_venue(self) -> Venue:

        venue = Venue(
            name=self.name,
            priority=self.priority,
            location=self.location,
            allows_attendee_content=self.allows_attendee_content,
            capacity=self.capacity,
        )

        for type, (start, end) in self.timeblocks.items():
            for day in islice(config.event_days, 1, None):
                start_dt = datetime.combine(day, start)
                if start.hour < 5:
                    start_dt = start_dt + timedelta(days=1)

                end_dt = datetime.combine(day, end)
                if end.hour < 5:
                    end_dt = end_dt + timedelta(days=1)

                automatic = False
                if type in ("talk", "workshop"):
                    automatic = True

                venue.time_blocks.append(
                    TimeBlock(start=start_dt, end=end_dt, type=type, automatic=automatic)
                )

        return venue


# This lives only here, on purpose, because this is just intended to seed the DB.
_EMF_VENUES = [
    VenueDefinition(
        name="Stage A",
        priority=100,
        latlon=(52.03961, -2.37787),
        allows_attendee_content=False,
        capacity=1000,
        timeblocks={"talk": (time(10), time(19))},
    ),
    VenueDefinition(
        name="Stage B",
        priority=99,
        latlon=(52.04190, -2.37664),
        allows_attendee_content=False,
        capacity=600,
        timeblocks={"talk": (time(10), time(19))},
    ),
    VenueDefinition(
        name="Stage C",
        priority=98,
        latlon=(52.04050, -2.37765),
        allows_attendee_content=False,
        capacity=450,
        timeblocks={"talk": (time(10), time(19)), "film": (time(19), time(1))},
    ),
    VenueDefinition(
        name="Stage D",
        priority=98,
        latlon=(52.04050, -2.37765),
        allows_attendee_content=False,
        capacity=450,
        timeblocks={"performance": (time(12), time(0))},
    ),
    VenueDefinition(
        name="Workshop 1",
        priority=97,
        latlon=(52.04259, -2.37515),
        allows_attendee_content=False,
        capacity=30,
        timeblocks={"workshop": (time(10), time(18))},
    ),
    VenueDefinition(
        name="Workshop 2",
        priority=96,
        latlon=(52.04208, -2.37715),
        allows_attendee_content=False,
        capacity=30,
        timeblocks={"workshop": (time(10), time(18))},
    ),
    VenueDefinition(
        name="Workshop 3",
        priority=95,
        latlon=(52.04129, -2.37578),
        allows_attendee_content=False,
        capacity=30,
        timeblocks={"workshop": (time(10), time(18))},
    ),
    VenueDefinition(
        name="Workshop 4",
        priority=94,
        latlon=(52.04329, -2.37590),
        allows_attendee_content=False,
        capacity=30,
        timeblocks={"workshop": (time(10), time(18))},
    ),
    VenueDefinition(
        name="Workshop 5",
        priority=93,
        latlon=(52.040938, -2.37706),
        allows_attendee_content=False,
        capacity=30,
        timeblocks={"workshop": (time(10), time(18))},
    ),
    VenueDefinition(
        name="Family Workshop",
        priority=92,
        latlon=(52.04117, -2.37771),
        allows_attendee_content=False,
        capacity=30,
        timeblocks={"familyworkshop": (time(10), time(18))},
    ),
    VenueDefinition(
        name="Main Bar",
        priority=91,
        latlon=(52.04180, -2.37727),
        allows_attendee_content=True,
        capacity=None,
        timeblocks={},
    ),
    VenueDefinition(
        name="Lounge",
        priority=90,
        latlon=(52.04147, -2.37644),
        allows_attendee_content=True,
        capacity=None,
        timeblocks={},
    ),
]


@dev_cli.command("venues")
def create_venues():
    """Create venues defined in code"""
    created = updated = 0
    for venue_definition in _EMF_VENUES:
        venue = db.session.query(Venue).filter_by(name=venue_definition.name).all()
        if venue:
            continue

        db.session.add(venue_definition.as_venue())
        created += 1

    db.session.commit()
    app.logger.info(f"Created {created} and updated {updated} venues.")


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


@dev_cli.command("pkpass")
@click.option("--email", default=None, help="User to build the pass for (default: first user).")
@click.option(
    "--out", "outfile", type=click.Path(), help="File to write (default: signed.pkpass or unsigned.pkpass)"
)
@click.option(
    "--signed", "signed", is_flag=True, help="Sign the pkpass using the certificate specified in config"
)
def dump_pkpass(email, outfile=None, signed=False):
    """Write a signed or unsigned .pkpass for previewing artwork/layout (e.g. in Wallet Pass Designer)."""

    user = User.query.filter_by(email=email).one() if email else User.query.first()
    if user is None:
        raise click.ClickException("No users found; run `flask dev data` first.")
    if signed:
        pkpass = generate_pkpass(user)
        if outfile is None:
            outfile = "signed.pkpass"
    else:
        pkpass = generate_unsigned_pkpass(user)
        if outfile is None:
            outfile = "unsigned.pkpass"
    with open(outfile, "wb") as f:
        f.write(pkpass.read())
    click.echo(f"Wrote pass for {user.email} to {outfile}")


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
