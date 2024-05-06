from random import sample

from flask import (
    flash,
    redirect,
    render_template,
    request,
    current_app as app,
    url_for,
)
from flask_mailman import EmailMessage

from main import db
from models.cfp import WorkshopProposal
from models.site_state import SiteState

from ..common.email import from_email

from . import cfp_review


@cfp_review.route("/lottery", methods=["GET", "POST"])
def lottery():
    # In theory this can be extended to other types but currently only workshops & youthworkshops care
    ticketed_proposals = WorkshopProposal.query.filter_by(requires_ticket=True).all()

    if request.method == "POST":
        winning_tickets = run_lottery(ticketed_proposals)
        flash(f"Lottery run. {len(ticketed_proposals)} tickets won.")
        return redirect(url_for(".lottery"))

    return render_template(
        "cfp_review/lottery.html", ticketed_proposals=ticketed_proposals
    )


def run_lottery(ticketed_proposals):
    """
    Here are the rules for the lottery.
    * Each user can only have one lottery ticket per workshop
    * A user's lottery tickets are ranked by preference
    * Drawings are done by rank
    * Once a user wins a lottery their other tickets are cancelled
    """
    # Copy because we don't want to change the original
    ticketed_proposals = ticketed_proposals.copy()
    lottery_round = 0

    winning_tickets = []

    app.logger.info(f"Found {len(ticketed_proposals)} proposals to run a lottery for")
    # Lock the lottery
    state = SiteState.query.get("signup_state")
    if not state:
        raise Exception("'signup_state' not found.")

    state.state = "pending_tickets"
    db.session.commit()

    while ticketed_proposals:
        app.logger.info(f"Starting round {lottery_round}")

        for proposal in ticketed_proposals:
            tickets_remaining = proposal.get_lottery_capacity()

            if tickets_remaining <= 0:
                app.logger.info(f"{proposal} is at capacity")
                ticketed_proposals.remove(proposal)
                continue

            current_rounds_lottery_tickets = [
                t for t in proposal.tickets if t.is_in_lottery_round(lottery_round)
            ]

            if len(current_rounds_lottery_tickets) == 0:
                app.logger.info(f"{proposal} has un-used lottery ticket capacity")
                ticketed_proposals.remove(proposal)
                continue

            # All tickets in this round get a place
            elif len(current_rounds_lottery_tickets) < tickets_remaining:
                for ticket in current_rounds_lottery_tickets:
                    ticket.won_lottery_and_cancel_others()
                    winning_tickets.append(ticket)
                    db.session.commit()

            # Not everyone at this rank will get a ticket so actually do the lottery
            else:
                for ticket in sample(current_rounds_lottery_tickets, tickets_remaining):
                    ticket.won_lottery_and_cancel_others()
                    winning_tickets.append(ticket)
                    db.session.commit()

                losing_lottery_tickets = [
                    t for t in proposal.tickets if t.state == "entered-lottery"
                ]

                for ticket in losing_lottery_tickets:
                    ticket.lost_lottery()
                    db.session.commit()
        lottery_round += 1

    app.logger.info(
        f"Issued {len(winning_tickets)} winning tickets over {lottery_round} rounds"
    )
    # Email winning tickets here
    # We should probably also check for users who didn't win anything?

    app.logger.info("sending emails")

    send_from = from_email("CONTENT_EMAIL")

    for ticket in winning_tickets:
        msg = EmailMessage(
            f"You have a ticket for the workshop '{ticket.proposal.title}'",
            from_email=send_from,
            to=[ticket.user.email],
        )

        msg.body = render_template(
            "emails/event_ticket_won.txt",
            user=ticket.user,
            proposal=ticket.proposal,
        )
