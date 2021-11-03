import click
from csv import DictReader

from faker import Faker
from flask import current_app as app

from main import db
from models.cfp import Proposal, TalkProposal, WorkshopProposal, InstallationProposal
from models.user import User
from apps.cfp_review.base import send_email_for_proposal

from . import cfp


@cfp.cli.command("import")
@click.argument("csv_file", type=click.File("r"))
@click.option(
    "-s",
    "--state",
    type=str,
    default="locked",
    help="The state to import the proposals as",
)
def csv_import(csv_file, state):
    """Import a previous schedule for testing"""
    faker = Faker()
    # id, title, description, length, need_finance,
    # one_day, type, experience, attendees, size
    reader = DictReader(csv_file)
    count = 0
    for row in reader:
        if Proposal.query.filter_by(title=row["title"]).first():
            continue

        user = User("cfp_%s@test.invalid" % count, faker.name())
        db.session.add(user)

        proposal = (
            TalkProposal()
            if row["type"] == u"talk"
            else WorkshopProposal()
            if row["type"] == u"workshop"
            else InstallationProposal()
        )

        proposal.state = state
        proposal.title = row["title"]
        proposal.description = row["description"]

        proposal.one_day = True if row.get("one_day") == "t" else False
        proposal.needs_money = True if row.get("need_finance") == "t" else False

        if row["type"] == "talk":
            proposal.length = row["length"]

        elif row["type"] == "workshop":
            proposal.length = row["length"]
            proposal.attendees = row["attendees"]

        else:
            proposal.size = row["size"]

        proposal.user = user
        db.session.add(proposal)

        db.session.commit()
        count += 1

    app.logger.info("Imported %s proposals" % count)


@cfp.cli.command("email_check")
def email_check():
    """Email speakers about their slot"""
    proposals = (
        Proposal.query.filter(Proposal.scheduled_duration.isnot(None))
        .filter(Proposal.state.in_(["accepted", "finished"]))
        .filter(Proposal.type.in_(["talk", "workshop", "youthworkshop", "performance"]))
        .all()
    )

    for proposal in proposals:
        send_email_for_proposal(
            proposal,
            reason="check-your-slot",
            from_address=app.config["SPEAKERS_EMAIL"],
        )


@cfp.cli.command("email_finalise")
def email_finalise():
    """Email speakers about finalising their talk"""
    proposals = (
        Proposal.query.filter(Proposal.scheduled_duration.isnot(None))
        .filter(Proposal.state.in_(["accepted"]))
        .filter(Proposal.type.in_(["talk", "workshop", "youthworkshop", "performance"]))
        .all()
    )

    for proposal in proposals:
        send_email_for_proposal(
            proposal,
            reason="please-finalise",
            from_address=app.config["SPEAKERS_EMAIL"],
        )


@cfp.cli.command("email_reserve")
def email_reserve():
    """Email speakers about reserve list"""
    proposals = (
        Proposal.query.filter(Proposal.state.in_(["reviewed"]))
        .filter(Proposal.type.in_(["talk", "workshop", "youthworkshop"]))
        .all()
    )

    for proposal in proposals:
        send_email_for_proposal(
            proposal, reason="reserve-list", from_address=app.config["SPEAKERS_EMAIL"]
        )
