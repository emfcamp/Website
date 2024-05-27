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
def lottery():
    # In theory this can be extended to other types but currently only workshops & youthworkshops care

    if get_signup_state() != "issue-lottery-tickets":
        raise Exception(f"Expected signup state to be 'issue-lottery-tickets'.")

    workshops = (
        WorkshopProposal.query.filter_by(requires_ticket=True, type="workshop")
        .filter(Proposal.state.in_(["accepted", "finalised"]))
        .all()
    )

    app.logger.info(f"Running lottery for {len(workshops)} workshops")
    winning_tickets = run_lottery(workshops)
    app.logger.info(f"{len(winning_tickets)} won")

    youthworkshops = (
        WorkshopProposal.query.filter_by(requires_ticket=True, type="youthworkshop")
        .filter(Proposal.state.in_(["accepted", "finalised"]))
        .all()
    )
    app.logger.info(f"Running lottery for {len(youthworkshops)} youthworkshops")
    winning_tickets = run_lottery(youthworkshops)
    app.logger.info(f"{len(winning_tickets)} won")


def run_lottery(ticketed_proposals):
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

    # This is the only state for running the lottery
    signup.state = "run-lottery"
    db.session.flush()
    refresh_states()


    max_rank = db.session.query(func.max(EventTicket.rank)).scalar() + 1
    proposal_capacities = {p.id: p.get_lottery_capacity() for p in ticketed_proposals}
    winning_tickets = []

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

    app.logger.info(
        f"Issued {len(winning_tickets)} winning tickets over {lottery_round} rounds"
    )

    signup.state = "pending-tickets"
    db.session.commit()
    db.session.flush()
    refresh_states()

    # Email winning tickets here
    # We should probably also check for users who didn't win anything?

    app.logger.info("sending emails")
    send_from = from_email("CONTENT_EMAIL")

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
        msg.send()

    return winning_tickets
