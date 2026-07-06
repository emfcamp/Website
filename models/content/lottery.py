from random import choices
from typing import TYPE_CHECKING, Literal, get_args

import sqlalchemy
from sqlalchemy import ForeignKey, func, select
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from main import db

from .. import BaseModel, bucketise, export_attr_counts
from ..user import User

if TYPE_CHECKING:
    from .schedule import Occurrence, ScheduleItem

__all__ = [
    "Lottery",
    "LotteryEntry",
    "LotteryEntryException",
]

LotteryState = Literal["closed", "allow-entry", "running-lottery", "completed", "sign-up-list"]

# entered -- an entry in the lottery for a number of tickets
# valid-tickets -- either a winning lottery entry or a simply issued ticket
# cancelled -- withdrawn/returned. Either as an actual ticket or a lottery ticket
LotteryEntryState = Literal["entered", "valid-tickets", "cancelled"]

LOTTERY_ENTRY_STATE_TRANSITIONS: dict[LotteryState, dict[LotteryEntryState, list[LotteryEntryState]]] = {
    "closed": {"entered": ["cancelled"]},
    "allow-entry": {
        "entered": ["cancelled"],
        "cancelled": ["entered"],
    },
    "running-lottery": {
        "entered": ["cancelled", "valid-tickets"],
        "valid-tickets": ["cancelled"],
    },
    "completed": {
        "valid-tickets": ["cancelled"],
    },
    "sign-up-list": {
        "entered": ["cancelled"],
        "valid-tickets": ["cancelled"],
        "cancelled": ["valid-tickets"],
    },
}

SAFECHARS = "2346789BCDFGHJKMPQRTVWXY"


class LotteryEntryException(Exception):
    pass


class Lottery(BaseModel):
    __tablename__ = "lottery"
    id: Mapped[int] = mapped_column(primary_key=True)
    state: Mapped[LotteryState] = mapped_column(
        sqlalchemy.Enum(
            *get_args(LotteryState),
            native_enum=False,
        ),
        default="closed",
    )

    #: The capacity of this schedule item, covering all ticket types. We don't count the stewards, presenters, or assistants.
    total_tickets: Mapped[int | None]
    #: Tickets that are reserved for on-the-door. The available lottery tickets are total_tickets - reserved_tickets.
    reserved_tickets: Mapped[int | None] = mapped_column(default=5)
    reserved_tickets_used: Mapped[int] = mapped_column(default=0, server_default="0")
    max_tickets_per_entry: Mapped[int]

    occurrence: Mapped[Occurrence] = relationship(back_populates="lottery")
    entries: Mapped[list[LotteryEntry]] = relationship(back_populates="lottery")

    schedule_item: AssociationProxy[ScheduleItem] = association_proxy("occurrence", "schedule_item")

    def get_all_ticket_capacity(self):
        return self.total_tickets - self.sum_tickets_in_state("valid-tickets")

    def get_lottery_capacity(self):
        return self.get_all_ticket_capacity() - self.reserved_tickets

    def sum_tickets_in_state(self, state: str) -> int:
        return sum([t.ticket_count for t in self.entries if t.state == state])

    def sum_ticket_codes_used(self) -> int:
        return len([t for e in self.entries for t in e.ticket_codes if t.used == True])

    def sum_ticket_codes_unused(self) -> int:
        return len([t for e in self.entries for t in e.ticket_codes if t.used == False])


class LotteryTicketCode(BaseModel):
    __tablename__ = "lottery_ticket_code"
    id: Mapped[int] = mapped_column(primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("lottery_entry.id"))
    code: Mapped[str]
    used: Mapped[bool] = mapped_column(default=False)

    entry: Mapped[LotteryEntry] = relationship(back_populates="ticket_codes")


class LotteryEntry(BaseModel):
    __tablename__ = "lottery_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    state: Mapped[LotteryEntryState]
    lottery_id: Mapped[int] = mapped_column(ForeignKey("lottery.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    rank: Mapped[int | None]
    ticket_count: Mapped[int] = mapped_column(default=1)

    lottery: Mapped[Lottery] = relationship(back_populates="entries")
    user: Mapped[User] = relationship(back_populates="lottery_entries")
    ticket_codes: Mapped[list[LotteryTicketCode]] = relationship(back_populates="entry")

    occurrence: AssociationProxy[Occurrence] = association_proxy("lottery", "occurrence")

    def get_users_other_lottery_entries_for_type(self) -> list[LotteryEntry]:
        return [
            e
            for e in self.user.lottery_entries
            if e.state == "entered"
            and e != self
            and e.occurrence.schedule_item.type == self.occurrence.schedule_item.type
        ]

    def is_in_lottery_round(self, round_rank):
        return self.state == "entered" and self.rank <= round_rank

    def change_state(self, new_state: LotteryEntryState) -> None:
        if new_state == self.state:
            return

        if new_state not in get_args(LotteryEntryState):
            raise LotteryEntryException(f"invalid lottery entry state {new_state}")

        valid_transitions = LOTTERY_ENTRY_STATE_TRANSITIONS[self.lottery.state]
        if new_state not in valid_transitions[self.state]:
            raise LotteryEntryException(
                f"invalid state transition {self.state} -> {new_state} whilst in {self.lottery.state}"
            )

        self.state = new_state

    def generate_codes(self) -> None:
        # These are in no way cryptographically secure etc but 1 in 308m should
        # be low enough odds for guessing.
        for _ in range(self.ticket_count):
            db.session.add(
                LotteryTicketCode(
                    entry=self,
                    code="".join(choices(SAFECHARS, k=6)),
                )
            )

    def won_lottery_and_cancel_others(self):
        self.change_state("valid-tickets")
        self.generate_codes()

        # Now cancel other lottery entries
        # This feels a bit icky locking-wise, as we don't lock the other Lotteries.
        # Perhaps we should combine multiple Lotteries into a SuperLottery somehow?
        for other_entry in self.get_users_other_lottery_entries_for_type():
            other_entry.cancel()

    def lost_lottery(self):
        self.change_state("cancelled")

    def cancel(self):
        if self.state == "entered":
            for entry in self.get_users_other_lottery_entries_for_type():
                if (entry.id == self.id) or (entry.rank < self.rank):
                    continue
                entry.rank -= 1
        return self.change_state("cancelled")

    def reenter_lottery(self) -> None:
        self.rank = get_max_rank_for_user(self.user, self.occurrence.schedule_item.type)
        return self.change_state("entered")

    @classmethod
    def create_entry(cls, user: User, lottery: Lottery, ticket_count: int = 1) -> LotteryEntry:
        # When would this ever happen?
        if ticket_count <= 0:
            raise LotteryEntryException("ticket_count must be greater than 0")

        if lottery.state == "allow-entry":
            if ticket_count <= lottery.get_lottery_capacity():
                rank = get_max_rank_for_user(user, lottery.schedule_item.type)
                return LotteryEntry(
                    state="entered", user=user, lottery=lottery, ticket_count=ticket_count, rank=rank
                )

            raise LotteryEntryException("This lottery is currently full.")

        if lottery.state == "sign-up-list":
            if ticket_count <= lottery.get_all_ticket_capacity():
                entry = LotteryEntry(
                    state="valid-tickets", user=user, lottery=lottery, ticket_count=ticket_count
                )
                entry.generate_codes()
                return entry

            raise LotteryEntryException(f"This {lottery.schedule_item.human_type} is currently full.")

        raise LotteryEntryException("This lottery is not currently open")

    @classmethod
    def get_export_data(cls):
        user_count_subq = (
            select(cls.user_id, func.count().label("user_count")).group_by(cls.user_id).subquery()
        )
        user_count_q = select(user_count_subq.c.user_count, func.count()).group_by(
            user_count_subq.c.user_count
        )

        lottery_count_subq = (
            select(cls.lottery_id, func.count().label("lottery_count")).group_by(cls.lottery_id).subquery()
        )
        lottery_count_q = select(lottery_count_subq.c.lottery_count, func.count()).group_by(
            lottery_count_subq.c.lottery_count
        )

        data = {
            "public": {
                "counts": {
                    "users": bucketise(
                        db.session.execute(user_count_q),
                        [0, 10, 20, 30, 40, 50],
                    ),
                    "lottery_count": bucketise(
                        db.session.execute(lottery_count_q),
                        [0, 10, 20, 30, 40, 50, 100, 150, 200, 250, 300, 350, 400, 450, 500],
                    ),
                }
            }
        }
        data["public"]["counts"].update(export_attr_counts(cls, ["state", "rank", "ticket_count"]))
        return data


def get_max_rank_for_user(user, schedule_item_type):
    return len(
        [
            le
            for le in user.lottery_entries
            if le.state == "entered" and le.occurrence.schedule_item.type == schedule_item_type
        ]
    )
