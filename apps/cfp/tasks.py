import click
from csv import DictReader

from faker import Faker
from flask import current_app as app

from main import db
from models.cfp import Proposal, TalkProposal, WorkshopProposal, InstallationProposal
from models.cfp_tag import Tag, DEFAULT_TAGS
from models.user import User
from apps.cfp_review.base import send_email_for_proposal
from ..common.email import from_email

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
            if row["type"] == "talk"
            else WorkshopProposal()
            if row["type"] == "workshop"
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
        .filter(Proposal.is_accepted)
        .filter(Proposal.type.in_(["talk", "workshop", "youthworkshop", "performance"]))
        .all()
    )

    for proposal in proposals:
        send_email_for_proposal(
            proposal,
            reason="check-your-slot",
            from_address=from_email("SPEAKERS_EMAIL"),
        )


@cfp.cli.command("email_finalise")
def email_finalise():
    """Email speakers about finalising their talk"""
    proposals = (
        Proposal.query.filter(Proposal.state.in_(["accepted"]))
        .filter(Proposal.type.in_(["talk", "workshop", "youthworkshop", "performance"]))
        .all()
    )

    for proposal in proposals:
        if not proposal.scheduled_duration:
            app.logger.info(
                "SKIPPING proposal %s due to lack of a scheduled duration. Set a duration!",
                proposal.id,
            )
            continue

        send_email_for_proposal(
            proposal,
            reason="please-finalise",
            from_address=from_email("SPEAKERS_EMAIL"),
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
            proposal, reason="reserve-list", from_address=from_email("SPEAKERS_EMAIL")
        )


@cfp.cli.command(
    "create_tags",
    help=f"Add tags to the database. Defaults are {DEFAULT_TAGS}.",
)
@click.argument("tags_to_create", nargs=-1)
def create_tags(tags_to_create):
    """Upsert tag list"""
    if not tags_to_create:
        tags_to_create = DEFAULT_TAGS

    tags_created = 0
    for tag in tags_to_create:
        if Tag.query.filter_by(tag=tag).all():
            app.logger.info(f"'{tag}' already exists, skipping.")
            continue

        db.session.add(Tag(tag))
        tags_created += 1
        app.logger.info(f"'{tag}' added to session.")

    db.session.commit()
    app.logger.info(f"Successfully created {tags_created} new tags.")


@cfp.cli.command(
    "delete_tags",
    help=f"Delete tags from the Database. Tagged proposals will have the tags removed.",
)
@click.argument("tags_to_delete", required=True, nargs=-1)
def delete_tags(tags_to_delete):
    """Delete tag list"""
    tags_deleted = 0
    for tag_name in tags_to_delete:
        tag = Tag.query.filter_by(tag=tag_name).one_or_none()
        if not tag:
            app.logger.info(f"Couldn't find tag: '{tag_name}' exiting.")
            return

        if tag.proposals:
            tagged_proposals = [p.id for p in tag.proposals]
            app.logger.info(
                f"'{tag_name}' will be removed from the proposals with ids: {tagged_proposals}"
            )

        db.session.delete(tag)
        tags_deleted += 1
        app.logger.info(f"'{tag_name}' added to session.")

    db.session.commit()
    app.logger.info(f"Successfully deleted {tags_deleted} tags.")
