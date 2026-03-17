import click

from random import shuffle
from sqlalchemy import func

from flask import render_template, current_app as app
from flask_mailman import EmailMessage

from main import db
from models.cfp import WorkshopProposal, Proposal
from models.event_tickets import EventTicket
from models.site_state import SiteState, refresh_states, get_signup_state

from ..common.email import from_email

from . import cfp


@cfp.cli.command("lottery")
@click.option("--dry-run/--no-dry-run", default=True, help="Actually run the lottery")
def lottery(dry_run):
    # In theory this can be extended to other types but currently only workshops & youthworkshops care

    if dry_run:
        app.logger.info(f"'dry-run' is set, lottery results will not be saved, to run use '--no-dry-run'")
    else:
        app.logger.info(f"'no-dry-run' is set, running lottery")

    if get_signup_state() not in ["issue-lottery-tickets", "run-lottery"]:
        raise Exception(f"Expected signup state to be 'issue-lottery-tickets'.")

    workshops = (
        WorkshopProposal.query.filter_by(requires_ticket=True, type="workshop")
        .filter(Proposal.state.in_(["accepted", "finalised"]))
        .all()
    )

    app.logger.info(f"Running lottery for {len(workshops)} workshops")
    winning_tickets = run_lottery(workshops, dry_run)
    app.logger.info(f"{len(winning_tickets)} won")

    youthworkshops = (
        WorkshopProposal.query.filter_by(requires_ticket=True, type="youthworkshop")
        .filter(Proposal.state.in_(["accepted", "finalised"]))
        .all()
    )
    app.logger.info(f"Running lottery for {len(youthworkshops)} youthworkshops")
    winning_tickets = run_lottery(youthworkshops, dry_run)
    app.logger.info(f"{len(winning_tickets)} won")


def run_lottery(ticketed_proposals, dry_run=False):
    """
    Here are the rules for the lottery.
    * Each user can only have one lottery ticket per workshop
    * A user's lottery tickets are ranked by preference
    * Drawings are done by rank
    * Once a user wins a lottery their other tickets are cancelled
    """
    lottery_round = 0

    winning_tickets = []

    app.logger.info(f"Found {len(ticketed_proposals)} proposals to run a lottery for")
    # Lock the lottery
    signup = SiteState.query.get("signup_state")
    if not signup:
        raise Exception("'signup_state' not found.")

    initial_state = signup.state  # only used for dry-run mode

    # This is the only state for running the lottery
    signup.state = "run-lottery"
    db.session.flush()
    refresh_states()

    max_rank = db.session.query(func.max(EventTicket.rank)).scalar() + 1
    proposal_capacities = {p.id: p.get_lottery_capacity() for p in ticketed_proposals}
    winning_tickets = []

    all_lottery_ticket_holders = {t.user for t in EventTicket.query.filter_by(state="enter-lottery").all()}

    for lottery_round in range(max_rank):
        for proposal in ticketed_proposals:
            tickets_remaining = proposal_capacities[proposal.id]

            tickets_for_round = [t for t in proposal.tickets if t.is_in_lottery_round(lottery_round)]
            shuffle(tickets_for_round)

            if tickets_remaining <= 0:
                for ticket in tickets_for_round:
                    ticket.lost_lottery()
                continue

            for ticket in tickets_for_round:
                if ticket.ticket_count <= tickets_remaining:
                    ticket.won_lottery_and_cancel_others()
                    winning_tickets.append(ticket)
                    tickets_remaining -= ticket.ticket_count
                else:
                    ticket.lost_lottery()

            proposal_capacities[proposal.id] = tickets_remaining

    app.logger.info(f"Issued {len(winning_tickets)} winning tickets over {lottery_round} rounds")

    format_string = "{: >80s} {: >15} {: >15} {: >15}  {: >10}  {: >10}"
    app.logger.info(
        format_string.format(
            "title", "total tickets", "lottery-tickets", "entered-lottery", "ticket", "cancelled"
        )
    )
    for prop in ticketed_proposals:
        counts = {
            "entered-lottery": 0,
            "ticket": 0,
            "cancelled": 0,
        }

        for ticket in prop.tickets:
            counts[ticket.state] += 1

        app.logger.info(
            format_string.format(
                prop.title,
                prop.total_tickets,
                (prop.total_tickets - prop.non_lottery_tickets),
                counts["entered-lottery"],
                counts["ticket"],
                counts["cancelled"],
            )
        )

    if dry_run:
        app.logger.info("Undoing lottery")
        db.session.rollback()
        # Reset the state
        signup.state = initial_state
    else:
        app.logger.info("Saving lottery result")
        signup.state = "pending-tickets"
    db.session.commit()
    db.session.flush()
    refresh_states()

    losing_ticket_holders = all_lottery_ticket_holders - {t.user for t in winning_tickets}
    app.logger.info(f"people who didn't win a ticket are: {losing_ticket_holders}")

    # Email winning tickets here
    # We should probably also check for users who didn't win anything?
    app.logger.info("sending emails")
    send_from = from_email("CONTENT_EMAIL")

    sent_emails = 0
    for ticket in winning_tickets:
        msg = EmailMessage(
            f"You have a ticket for the {ticket.proposal.human_type} '{ticket.proposal.title}'",
            from_email=send_from,
            to=[ticket.user.email],
        )

        msg.body = render_template(
            "emails/event_ticket_won.txt",
            user=ticket.user,
            proposal=ticket.proposal,
            ticket=ticket,
        )
        sent_emails += 1
        if dry_run:
            continue
        msg.send()

    if dry_run:
        app.logger.info(f"Would have sent {sent_emails} emails for {len(winning_tickets)} winners")
    else:
        app.logger.info(f"sent {sent_emails} emails for {len(winning_tickets)} winners")

    return winning_tickets
