import click
from flask_mail import Message

from main import mail, db
from apps.base import base as app
from models.user import User
from models.permission import Permission
from models.email import EmailJobRecipient


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
    """ Make a user in the DB an admin """
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
    """ Create permissions in DB if they don't exist """
    for permission in (
        "admin",
        "arrivals",
        "cfp_reviewer",
        "cfp_anonymiser",
        "cfp_schedule",
    ):
        if not Permission.query.filter_by(name=permission).first():
            db.session.add(Permission(permission))

    db.session.commit()


@app.cli.command("send_emails")
def send_emails():
    with mail.connect() as conn:
        for rec in EmailJobRecipient.query.filter(
            EmailJobRecipient.sent == False
        ):  # noqa: E712
            send_email(conn, rec)


def send_email(conn, rec):
    msg = Message(rec.job.subject, sender=app.config["CONTACT_EMAIL"])
    msg.add_recipient(rec.user.email)
    msg.body = rec.job.text_body
    msg.html = rec.job.html_body
    conn.send(msg)
    rec.sent = True
    db.session.add(rec)
    db.session.commit()
