import click

from main import db
from apps.base import base as app
from models.user import User
from models.permission import Permission
from models.scheduled_task import execute_scheduled_tasks
from models.feature_flag import FeatureFlag, refresh_flags, DB_FEATURE_FLAGS
from models.site_state import SiteState, refresh_states, VALID_STATES


@app.cli.command("periodic")
@click.option(
    "-f",
    "--force/--no-force",
    default=False,
    help="Run all tasks regardless of schedule",
)
def periodic(force):
    """Execute periodic scheduled tasks"""
    execute_scheduled_tasks(force)


@app.cli.command("make_admin")
@click.option("-u", "--user-id", type=int, help="The user_id to make an admin (defaults to first)")
@click.option(
    "-e",
    "--email",
    type=str,
    help="Create a new user with this e-mail and make them an admin",
)
def make_admin(user_id, email):
    """Make a user in the DB an admin"""
    if email:
        user = User(email, "Initial Admin User")
        db.session.add(user)
        db.session.commit()
    elif user_id:
        user = User.query.get(user_id)
    else:
        user = User.query.order_by(User.id).first()

    if not user:
        click.echo("No user exists or matches the search.")
        return

    user.grant_permission("admin")
    db.session.commit()

    click.echo("%r is now an admin" % user.name)


@app.cli.command("create_perms")
def create_perms():
    """Create permissions in DB if they don't exist"""
    for permission in (
        "admin",
        "arrivals:checkin",
        "arrivals:merch",
        "cfp_admin",
        "cfp_reviewer",
        "cfp_anonymiser",
        "cfp_schedule",
        "villages",
        "volunteer:admin",
        "volunteer:manager",
    ):
        if not Permission.query.filter_by(name=permission).first():
            db.session.add(Permission(permission))

    db.session.commit()


@app.cli.command("set_flag")
@click.argument("flag_names", nargs=-1)
@click.option("--enable/--disable", default=True)
def set_flag(flag_names, enable):
    for flag in flag_names:
        current = FeatureFlag.query.filter_by(feature=flag).one_or_none()
        if current:
            current.enabled = enable
        else:
            db.session.add(FeatureFlag(feature=flag, enabled=enable))

        if enable:
            print(f"enabling flag: '{flag}'")
        else:
            print(f"disabling flag: '{flag}'")

        if flag not in DB_FEATURE_FLAGS:
            print(f"[WARN] flag ({flag}) not in DB_FEATURE_FLAGS")
    db.session.commit()
    refresh_flags()


@app.cli.command("set_site_state")
@click.argument("state_name", nargs=1)
@click.argument("state", nargs=1)
def set_site_state(state_name, state):
    if state_name not in VALID_STATES:
        print(f"[WARN] state name ({state_name}) not in VALID_STATES")
    elif state not in VALID_STATES[state_name]:
        print(f"[WARN] state ({state}) not found in valid states for {state_name}")

    current = SiteState.query.filter_by(name=state_name).one_or_none()
    if not current:
        db.session.add(SiteState(name=state_name, state=state))
    else:
        current.state = state
    print(f"set '{state_name}' to state '{state}'")
    db.session.commit()
    refresh_states()
