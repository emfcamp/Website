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

LotteryState = Literal["closed", "allow-entry", "running-lottery", "completed", "first-come-first-served"]

# entered -- an entry in the lottery for a number of tickets
# valid-tickets -- either a winning lottery entry or a simply issued ticket
# cancelled -- withdrawn/returned. Either as an actual ticket or a lottery ticket
LotteryEntryState = Literal["entered", "valid-tickets", "cancelled"]

LOTTERY_ENTRY_STATE_TRANSITIONS: dict[LotteryState, dict[LotteryEntryState, list[LotteryEntryState]]] = {
    "closed": {},
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
    "first-come-first-served": {
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

    total_tickets: Mapped[int | None]
    reserved_tickets: Mapped[int | None] = mapped_column(default=5)
    max_tickets_per_entry: Mapped[int]

    occurrence: Mapped["Occurrence"] = relationship(back_populates="lottery")
    entries: Mapped[list["LotteryEntry"]] = relationship(back_populates="lottery")

    schedule_item: AssociationProxy["ScheduleItem"] = association_proxy("occurrence", "schedule_item")

    def get_all_ticket_capacity(self):
        return self.total_tickets - self.sum_tickets_in_state("valid-tickets")

    def get_lottery_capacity(self):
        return self.get_all_ticket_capacity() - self.reserved_tickets

    def sum_tickets_in_state(self, state: str) -> int:
        return sum([t.ticket_count for t in self.entries if t.state == state])


class LotteryEntry(BaseModel):
    __tablename__ = "lottery_entry"

    id: Mapped[int] = mapped_column(primary_key=True)
    state: Mapped[LotteryEntryState]
    lottery_id: Mapped[int] = mapped_column(ForeignKey("lottery.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    rank: Mapped[int | None]
    ticket_count: Mapped[int] = mapped_column(default=1)
    ticket_codes: Mapped[str | None]

    lottery: Mapped[Lottery] = relationship(back_populates="entries")
    user: Mapped[User] = relationship(back_populates="lottery_entries")

    occurrence: AssociationProxy["Occurrence"] = association_proxy("lottery", "occurrence")

    # add a way to indicate a code has been used?
    def use_code(self, code):
        all_codes = self.ticket_codes.split(",")
        if code not in all_codes:
            raise LotteryEntryException(f"Code '{code}' not found")

        all_codes.remove(code)
        self.ticket_codes = ",".join(all_codes)

    def use_all_codes(self):
        if not self.ticket_codes:
            raise LotteryEntryException("No codes found")
        self.ticket_codes = ""

    def get_users_other_lottery_entries_for_type(self):
        return [
            e
            for e in self.user.lottery_entries
            if e.state == "entered" and e != self and e.schedule_item.type == self.schedule_item.type
        ]

    def is_in_lottery_round(self, round_rank):
        return self.state == "entered" and self.rank <= round_rank

    def change_state(self, new_state):
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

    def generate_codes(self):
        # These are in no way cryptographically secure etc but 1 in 308m should
        # be low enough odds for guessing.
        codes = []
        for _ in range(self.ticket_count):
            codes.append("".join(choices(SAFECHARS, k=6)))
        self.ticket_codes = ",".join(codes)

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

    def reenter_lottery(self):
        self.rank = get_max_rank_for_user(self.user, self.schedule_item.type)
        return self.change_state("entered")

    @classmethod
    def create_entry(cls, user: User, lottery: Lottery, ticket_count: int = 1) -> "LotteryEntry":
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

        if lottery.state == "first-come-first-served":
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
