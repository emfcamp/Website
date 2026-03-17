from random import choices

from sqlalchemy import ForeignKey, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from main import db

from . import BaseModel, bucketise, export_attr_counts
from .cfp import Proposal
from .site_state import get_signup_state
from .user import User

__all__ = [
    "EventTicket",
    "EventTicketException",
]

# entered-lottery -- An entry in the lottery for a ticket
# ticket -- either a converted lottery ticket or a simply issued ticket
# cancelled -- with drawn/returned. Either as an actual ticket or a lottery ticket

EVENT_TICKET_STATES = {"entered-lottery", "ticket", "cancelled"}

EVENT_TICKET_STATE_TRANSITIONS = {
    "closed": {},
    "issue-lottery-tickets": {
        "entered-lottery": ["cancelled"],
        "cancelled": ["entered-lottery"],
    },
    "run-lottery": {
        "entered-lottery": ["cancelled", "ticket"],
        "ticket": ["cancelled"],
    },
    "pending-tickets": {
        "ticket": ["cancelled"],
    },
    "issue-event-tickets": {
        "ticket": ["cancelled"],
        "cancelled": ["ticket"],
    },
}

SAFECHARS = "2346789BCDFGHJKMPQRTVWXY"


class EventTicketException(Exception):
    pass


class EventTicket(BaseModel):
    __tablename__ = "event_ticket"

    id: Mapped[int] = mapped_column(primary_key=True)
    state: Mapped[str]
    proposal_id: Mapped[int] = mapped_column(ForeignKey("proposal.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    rank: Mapped[int | None]
    ticket_count: Mapped[int] = mapped_column(default=1)
    ticket_codes: Mapped[str | None]

    proposal: Mapped[Proposal] = relationship(back_populates="tickets")
    user: Mapped[User] = relationship(back_populates="event_tickets")

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

    # add a way to indicate a code has been used?
    def use_code(self, code):
        all_codes = self.ticket_codes.split(",")
        if code not in all_codes:
            raise EventTicketException(f"Code '{code}' not found")

        all_codes.remove(code)
        self.ticket_codes = ",".join(all_codes)
        return self

    def use_all_codes(self):
        if not self.ticket_codes:
            raise EventTicketException("No codes found")
        self.ticket_codes = ""
        return self

    def get_users_other_lottery_tickets_for_type(self):
        return [
            t
            for t in self.user.event_tickets
            if t.state == "entered-lottery" and t != self and t.proposal.type == self.proposal.type
        ]

    def is_in_lottery_round(self, round_rank):
        return self.state == "entered-lottery" and self.rank <= round_rank

    def change_state(self, new_state, *, force=False):
        # The force option only exists for ease of resetting this in dev
        if force:
            self.state = new_state
            return None

        if new_state == self.state:
            return self

        if new_state == "entered-lottery" and (self.rank is None or self.rank < 0):
            raise EventTicketException("lottery tickets must have a rank")

        if new_state != "entered-lottery":
            self.rank = None

        signup_state = get_signup_state()
        valid_transitions = EVENT_TICKET_STATE_TRANSITIONS[signup_state]

        try:
            if new_state not in valid_transitions[self.state]:
                raise EventTicketException(
                    f"invalid state transition {self.state} -> {new_state} whilst in {signup_state}"
                )
        except KeyError as e:
            raise EventTicketException(
                f"State, {self.state} not found in in {signup_state}, new state {new_state}"
            ) from e

        self.state = new_state
        return self

    def issue_codes(self):
        # Now generate the ticket_codes
        # These are in no way cryptographically secure etc but 1 in 308m should
        # be low enough odds for guessing.
        codes = []
        for _ in range(self.ticket_count):
            codes.append("".join(choices(SAFECHARS, k=6)))
        self.ticket_codes = ",".join(codes)
        return self

    def issue_ticket(self):
        self.change_state("ticket")
        self.issue_codes()
        return self

    def won_lottery_and_cancel_others(self):
        self.issue_ticket()

        # Now cancel other tickets
        for other_ticket in self.get_users_other_lottery_tickets_for_type():
            other_ticket.cancel()

        return self

    def lost_lottery(self):
        return self.change_state("cancelled")

    def cancel(self):
        if self.state == "entered-lottery":
            for ticket in self.get_users_other_lottery_tickets_for_type():
                if (ticket.id == self.id) or (ticket.rank < self.rank):
                    continue
                ticket.rank -= 1
        return self.change_state("cancelled")

    def reenter_lottery(self, *, force=False):
        # The force option only exists for ease of resetting this in dev
        self.rank = get_max_rank_for_user(self.user, self.proposal.type)
        return self.change_state("entered-lottery", force=force)

    @classmethod
    def get_event_ticket(cls, user: User, proposal: Proposal) -> "EventTicket | None":
        return db.session.execute(
            select(EventTicket).where(EventTicket.user_id == user.id, EventTicket.proposal_id == proposal.id)
        ).scalar_one_or_none()

    @classmethod
    def create_ticket(self, user, proposal, ticket_count=1):
        signup_state = get_signup_state()

        if signup_state == "issue-lottery-tickets":
            rank = get_max_rank_for_user(user, proposal.type)
            return EventTicket(user.id, proposal.id, "entered-lottery", ticket_count, rank)
        if signup_state == "issue-event-tickets" and (ticket_count <= proposal.get_total_capacity()):
            return EventTicket(user.id, proposal.id, "ticket", ticket_count).issue_codes()

        if signup_state == "issue-event-tickets" and not (ticket_count < proposal.get_total_capacity()):
            raise EventTicketException(f"This {proposal.human_type} is currently full.")

        raise EventTicketException("Tickets are not currently being issued")

    @classmethod
    def get_export_data(cls):
        user_count_subq = (
            select(cls.user_id, func.count().label("user_count")).group_by(cls.user_id).subquery()
        )
        user_count_q = select(user_count_subq.c.user_count, func.count()).group_by(
            user_count_subq.c.user_count
        )

        proposal_count_subq = (
            select(cls.proposal_id, func.count().label("proposal_count")).group_by(cls.proposal_id).subquery()
        )
        proposal_count_q = select(proposal_count_subq.c.proposal_count, func.count()).group_by(
            proposal_count_subq.c.proposal_count
        )

        data = {
            "public": {
                "counts": {
                    "users": bucketise(
                        db.session.execute(user_count_q),
                        [0, 10, 20, 30, 40, 50],
                    ),
                    "proposal_counts": bucketise(
                        db.session.execute(proposal_count_q),
                        [0, 10, 20, 30, 40, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500],
                    ),
                }
            }
        }
        data["public"]["counts"].update(export_attr_counts(cls, ["state", "rank", "ticket_count"]))
        return data


def get_max_rank_for_user(user, proposal_type):
    return len(
        [
            t
            for t in user.event_tickets.all()
            if t.state == "entered-lottery" and t.proposal.type == proposal_type
        ]
    )
