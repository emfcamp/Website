from typing import Any, TypeVar

from sqlalchemy import event
from sqlalchemy.orm import LoaderCallableStatus


class StateTransitionException(Exception):
    pass


TState = TypeVar("TState")


# TODO: this should become a column wrapper type
def validate_state_transitions(column: Any, allowed_transitions: dict[TState, set[TState]]) -> None:
    def on_state_set(target, value, oldvalue, initiator):
        if oldvalue == LoaderCallableStatus.NO_VALUE:
            return
        if value == oldvalue:
            return
        if value not in allowed_transitions[oldvalue]:
            raise StateTransitionException(f"{target} cannot transition from {oldvalue} to {value}")

    event.listen(column, "set", on_state_set)


from .cfp import *  # noqa: F403
from .lottery import *  # noqa: F403
from .schedule import *  # noqa: F403
from .tagging import *  # noqa: F403
from .venue import *  # noqa: F403
