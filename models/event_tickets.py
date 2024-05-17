from random import choices
from string import ascii_lowercase

from main import db
from . import BaseModel
from .user import User
from .cfp import Proposal


# entered-lottery -- An entry in the lottery for a ticket
# ticket -- either a converted lottery ticket or a simply issued ticket
# lost-lottery -- did not convert from a lottery ticket to an actual ticket
# cancelled -- with drawn/returned. Either as an actual ticket or a lottery ticket

EVENT_TICKET_STATES = {
    "entered-lottery": ["ticket", "lost-lottery", "cancelled"],
    "ticket": ["cancelled"],
    "lost-lottery": ["cancelled"],
    "cancelled": [],
}


class EventTicketException(Exception):
    pass


class EventTicket(BaseModel):
    __tablename__ = "event_ticket"

    id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String, nullable=False)
    proposal_id = db.Column(db.Integer, db.ForeignKey("proposal.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    rank = db.Column(db.Integer, nullable=True)
    ticket_count = db.Column(db.Integer, nullable=False, default=1)
    ticket_codes = db.Column(db.String, nullable=True)

    def __init__(self, user_id, proposal_id, state, ticket_count=1, rank=None):
        if state not in EVENT_TICKET_STATES:
            raise EventTicketException(f"invalid ticket state {state}")

        if state == "entered-lottery" and ((rank and rank < 0) or rank is None):
            raise EventTicketException("rank must be greater than or equal to 0")

        if ticket_count <= 0:
            raise EventTicketException("ticket_count must be greater than 0")

        self.user_id = user_id
        self.proposal_id = proposal_id
        self.state = state
        self.ticket_count = ticket_count
        self.rank = rank

    def get_other_lottery_tickets(self):
        return [
            t
            for t in self.user.event_tickets
            if t.state == "entered-lottery" and t != self
        ]

    def is_in_lottery_round(self, round_rank):
        return self.state == "entered-lottery" and self.rank <= round_rank

    def change_state(self, new_state):
        if new_state == "entered-lottery" and not self.rank:
            raise EventTicketException("lottery tickets must have a rank")

        if new_state not in EVENT_TICKET_STATES[self.state]:
            raise EventTicketException(
                f"invalid state transition {self.state} -> {new_state}"
            )

        self.state = new_state
        return self

    def won_lottery_and_cancel_others(self):
        self.change_state("ticket")
        # Now cancel other tickets
        for other_ticket in self.get_other_lottery_tickets():
            other_ticket.cancel()

        # Now generate the ticket_codes
        # These are in no way cryptographically secure etc but 1 in 308m should
        # be low enough odds for guessing.
        codes = []
        for i in range(self.ticket_count):
            codes.append("".join(choices(ascii_lowercase, k=6)))
        self.ticket_codes = ",".join(codes)

        return self

    def lost_lottery(self):
        return self.change_state("lost-lottery")

    def cancel(self):
        return self.change_state("cancelled")

    def cancel_and_update_ranks(self):
        # adjust ranks for lottery tickets
        if self.state == "entered-lottery":
            for ticket in self.get_other_lottery_tickets():
                if (ticket.id == self.id) or (ticket.rank < self.rank):
                    continue
                ticket.rank -= 1
        return self.cancel()

    @classmethod
    def get_event_ticket(cls, user: User, proposal: Proposal):
        return EventTicket.query.filter_by(
            user_id=user.id, proposal_id=proposal.id
        ).one_or_none()


def create_ticket(user: User, proposal: Proposal) -> EventTicket:
    return EventTicket(user.id, proposal.id, "ticket")


def create_lottery_ticket(
    user: User, proposal: Proposal, ticket_count=1, rank=None
) -> EventTicket:
    if rank is None:
        rank = len(user.event_tickets.all())

    return EventTicket(user.id, proposal.id, "entered-lottery", ticket_count, rank)
