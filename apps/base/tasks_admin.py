import click

from main import db
from apps.base import base as app
from models.user import User
from models.permission import Permission
from models.scheduled_task import execute_scheduled_tasks


@app.cli.command("periodic")
def periodic():
    """Execute periodic scheduled tasks"""
    execute_scheduled_tasks()


@app.cli.command("make_admin")
@click.option(
    "-u", "--user-id", type=int, help="The user_id to make an admin (defaults to first)"
)
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
        print("No user exists or matches the search.")
        return

    user.grant_permission("admin")
    db.session.commit()

    print("%r is now an admin" % user.name)


@app.cli.command("create_perms")
def create_perms():
    """Create permissions in DB if they don't exist"""
    for permission in (
        "admin",
        "arrivals",
        "cfp_admin",
        "cfp_reviewer",
        "cfp_anonymiser",
        "cfp_schedule",
        "villages",
    ):
        if not Permission.query.filter_by(name=permission).first():
            db.session.add(Permission(permission))

    db.session.commit()
