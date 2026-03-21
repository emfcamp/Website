import click

from random import shuffle
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from flask import render_template, current_app as app
from flask_mailman import EmailMessage

from main import db
from models.cfp import Occurrence, ScheduleItem
from models.lottery import LotteryEntry, Lottery

from ..common.email import from_email

from . import cfp


"""
Here are the rules for the lottery.
* Each user can only have one lottery ticket per lottery
* A user's lottery tickets are ranked by preference
* Drawings are done by rank
* Once a user wins a lottery their other tickets for that ScheduleItemType
  are cancelled. This is for fairness, so someone who enters one lottery
  has as much chance of winning as someone who enters loads. However, we
  don't prevent them entering a new lottery that opens up later.
"""


@cfp.cli.command("lottery")
@click.option("-t", "--type", type=str, help="Schedule item type")
@click.option("--dry-run/--no-dry-run", default=True, help="Actually run the lottery")
def lottery(schedule_item_type, dry_run) -> None:
    if dry_run:
        app.logger.info(f"'dry-run' is set, lottery results will not be saved, to run use '--no-dry-run'")
    else:
        app.logger.info(f"'no-dry-run' is set, running lottery")

    lotteries_to_lock: list[Lottery] = list(
        db.session.scalars(
            select(Lottery)
            .where(Lottery.state == "allow-entry")
            .join(Lottery.occurrence)
            .join(Occurrence.schedule_item)
            .where(ScheduleItem.type == schedule_item_type)
        )
    )

    app.logger.info(f"Found {len(lotteries_to_lock)} lotteries")

    # "Lock" the lotteries. TODO: should we actually lock here (and on entry creation)?
    for lottery in lotteries_to_lock:
        lottery.state = "running-lottery"
    db.session.commit()

    lotteries: list[Lottery] = list(
        db.session.scalars(
            select(Lottery)
            .where(Lottery.state == "running-lottery")
            .join(Lottery.schedule_item)
            .where(ScheduleItem.type == schedule_item_type)
            .options(selectinload(Lottery.occurrence).selectinload(Occurrence.schedule_item))
            .options(selectinload(Lottery.entries).selectinload(LotteryEntry.user))
        )
    )

    # Grab this before we change any states
    all_lottery_entry_holders = {
        e.user for lottery in lotteries for e in lottery.entries if e.state == "entered"
    }

    max_rank = db.session.query(func.max(LotteryEntry.rank)).scalar() + 1
    lottery_capacities = {lottery.id: lottery.get_lottery_capacity() for lottery in lotteries}
    winning_entries: list[LotteryEntry] = []

    lottery_round = 0
    for lottery_round in range(max_rank):
        for lottery in lotteries:
            tickets_remaining = lottery_capacities[lottery.id]

            entries_for_round = [t for t in lottery.entries if t.is_in_lottery_round(lottery_round)]
            shuffle(entries_for_round)

            if tickets_remaining <= 0:
                for entry in entries_for_round:
                    entry.lost_lottery()
                continue

            for entry in entries_for_round:
                if entry.ticket_count <= tickets_remaining:
                    entry.won_lottery_and_cancel_others()
                    winning_entries.append(entry)
                    tickets_remaining -= entry.ticket_count
                else:
                    entry.lost_lottery()

            lottery_capacities[lottery.id] = tickets_remaining

    app.logger.info(f"Issued {len(winning_entries)} winning entries over {lottery_round} rounds")

    format_string = "{: >80s} {: >15} {: >15} {: >15}  {: >10}  {: >10}"
    app.logger.info(
        format_string.format(
            "title", "total tickets", "lottery tickets", "entered", "valid-tickets", "cancelled"
        )
    )
    for lottery in lotteries:
        counts = {
            "entered": 0,
            "valid-tickets": 0,
            "cancelled": 0,
        }

        for entry in lottery.entries:
            counts[entry.state] += 1

        assert lottery.total_tickets is not None
        assert lottery.reserved_tickets is not None

        app.logger.info(
            format_string.format(
                lottery.schedule_item.title,
                lottery.total_tickets,
                (lottery.total_tickets - lottery.reserved_tickets),
                counts["entered"],
                counts["valid-tickets"],
                counts["cancelled"],
            )
        )

    if dry_run:
        app.logger.info("Undoing lottery")
        db.session.rollback()

    else:
        app.logger.info("Saving lottery result")
        for lottery in lotteries:
            lottery.state = "completed"

    if not dry_run:
        db.session.commit()

    losing_entry_holders = all_lottery_entry_holders - {t.user for t in winning_entries}
    app.logger.info(f"people who didn't win a ticket are: {losing_entry_holders}")

    # Email winning entries here
    # We should probably also check for users who didn't win anything?
    app.logger.info("sending emails")
    send_from = from_email("CONTENT_EMAIL")

    sent_emails = 0
    for entry in winning_entries:
        msg = EmailMessage(
            f"You won the lottery for the {entry.occurrence.schedule_item.human_type} '{entry.occurrence.schedule_item.title}'",
            from_email=send_from,
            to=[entry.user.email],
        )

        msg.body = render_template(
            "emails/lottery_entry_won.txt",
            user=entry.user,
            occurrence=entry.occurrence,
            entry=entry,
        )
        sent_emails += 1
        if dry_run:
            continue
        msg.send()

    if dry_run:
        app.logger.info(f"Would have sent {sent_emails} emails for {len(winning_entries)} winners")
        db.session.rollback()
    else:
        app.logger.info(f"sent {sent_emails} emails for {len(winning_entries)} winners")
