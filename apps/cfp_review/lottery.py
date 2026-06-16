from random import shuffle
from typing import get_args

from flask import abort, flash, redirect, render_template, url_for
from flask import current_app as app
from flask.typing import ResponseReturnValue
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload
from wtforms import SubmitField

from apps.cfp_review import admin_required as cfp_admin_required
from apps.cfp_review import cfp_review
from apps.common.email import enqueue_emails
from main import db
from models.content import Lottery, LotteryEntry, Occurrence, ScheduleItem, ScheduleItemType

from ..common.forms import Form
from ..config import config


class ConfirmRunLotteryForm(Form):
    confirm = SubmitField("Confirm and run")


@cfp_review.route("/lottery")
@cfp_admin_required
def lottery() -> ResponseReturnValue:
    # This includes closed lotteries
    ticketed_occurrences = list(db.session.scalars(select(Occurrence).where(Occurrence.lottery.has())))
    return render_template("cfp_review/lottery.html", ticketed_occurrences=ticketed_occurrences)


@cfp_review.route("/lottery/<schedule_item_type>", methods=["GET"])
@cfp_admin_required
def lotteries_for_type(schedule_item_type: str) -> ResponseReturnValue:
    if schedule_item_type not in get_args(ScheduleItemType):
        abort(404)

    lotteries: list[Lottery] = list(
        db.session.scalars(
            select(Lottery)
            .join(Lottery.occurrence)
            .join(Occurrence.schedule_item)
            .where(ScheduleItem.type == schedule_item_type)
        )
    )

    form = ConfirmRunLotteryForm()

    return render_template(
        "cfp_review/lotteries-for-type.html",
        lotteries=lotteries,
        schedule_item_type=schedule_item_type,
        form=form,
    )


@cfp_review.route("/lottery/<schedule_item_type>/run", methods=["POST"])
@cfp_admin_required
def run_lottery(schedule_item_type: str) -> ResponseReturnValue:
    if schedule_item_type not in get_args(ScheduleItemType):
        abort(404)

    """
    * Each user gets one lottery entry per lottery. This entry can count for multiple "tickets".
    * A user's lottery entries are ranked by preference (where 0 is their most preferred choice).
    * Draws for a ScheduleItemType are done for each Lottery in turn, and by rank, starting at 0.
    * Entries that miss out on a round are entered into the next round, along with entries from
      users who placed it at at the next level of preference down.
    * If the number of tickets in a winning entry exceeds the remaining capacity, that entry loses.
    * Once a user has a winning entry, their other tickets for that ScheduleItemType are cancelled.
      Someone who enters lots of lotteries has a higher chance of getting _something_, but it
      won't necessarily be a favourite. A drawn lottery is final and cannot be run again.
    * We don't prevent users entering a new lottery that opens up later for the same ScheduleItemType.
    """

    lotteries: list[Lottery] = list(
        db.session.scalars(
            select(Lottery)
            .where(Lottery.state == "allow-entry")
            .join(Lottery.occurrence)
            .join(Occurrence.schedule_item)
            .where(ScheduleItem.type == schedule_item_type)
            .options(selectinload(Lottery.occurrence).selectinload(Occurrence.schedule_item))
            .options(selectinload(Lottery.entries).selectinload(LotteryEntry.user))
            .with_for_update(of=Lottery)
        )
    )

    app.logger.info("Running lottery for type { schedule_item_type }")
    app.logger.debug(f"Found {len(lotteries)} lotteries")

    # TODO: we should also lock Lottery for update when adding entries
    for lottery in lotteries:
        # Transitional state that allows entries to be confirmed
        # This state will never be visible to another session.
        lottery.state = "running-lottery"
    db.session.flush()

    # Grab this before we change any states
    # all_lottery_entry_holders = {
    #    e.user for lottery in lotteries for e in lottery.entries if e.state == "entered"
    # }

    max_rank = db.session.query(func.max(LotteryEntry.rank)).scalar() + 1
    lottery_capacities = {lottery.id: lottery.get_lottery_capacity() for lottery in lotteries}
    winning_entries: list[LotteryEntry] = []

    lottery_round = 0
    for lottery_round in range(max_rank):
        for lottery in lotteries:
            tickets_remaining = lottery_capacities[lottery.id]

            entries_for_round = [e for e in lottery.entries if e.is_in_lottery_round(lottery_round)]
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

    for lottery in lotteries:
        lottery.state = "completed"

    # TODO: should we email users who didn't win anything?
    # losing_entry_holders = all_lottery_entry_holders - {t.user for t in winning_entries}
    # app.logger.info(f"People who didn't win a ticket are: {losing_entry_holders}")

    for entry in winning_entries:
        subject = f"You won the lottery for the {entry.occurrence.schedule_item.human_type} '{entry.occurrence.schedule_item.title}'"
        text_body = render_template(
            "emails/lottery-entry-won.txt",
            entry=entry,
        )
        enqueue_emails(
            users=[entry.user],
            from_email=config.from_email("CONTENT_EMAIL"),
            subject=subject,
            text_body=text_body,
            priority=1,
        )

    db.session.commit()
    msg = f"Issued {len(winning_entries)} winning entries over {lottery_round} rounds."
    app.logger.info(msg)
    flash(msg)

    return redirect(url_for(".lotteries_for_type", schedule_item_type=schedule_item_type))
