"""
Date functions to make it easier to deal with dates and times in content/scheduling.

The content system day changes over at 5am, so "3am on Friday" is actually Saturday in the more conventional calendar.
This module contains functions to convert between these two representations.

It seems messy but the alternative is worse.
"""

from collections.abc import Iterator
from datetime import date, datetime, time, timedelta

from models.content.schedule import ScheduleItemType

from ..config import config

#: The time that the "content day" starts - 5am
CONTENT_DAY_START = time(5)

#: Which day the "main" event content starts on, relative to EVENT_START
MAIN_CONTENT_START_DAY = 1


def content_days() -> Iterator[tuple[date, tuple[datetime, datetime]]]:
    """Iterate through event days, returning a tuple of (day, (day_start, day_end))."""
    for day in config.event_days:
        yield (
            day,
            (
                datetime.combine(day, CONTENT_DAY_START),
                datetime.combine(day + timedelta(days=1), CONTENT_DAY_START),
            ),
        )


def content_timestamp(content_day: date, time_val: time) -> datetime:
    """Convert a "content day" and a time into a real timestamp."""
    if time_val < CONTENT_DAY_START:
        real_day = content_day + timedelta(days=1)
    else:
        real_day = content_day

    return datetime.combine(real_day, time_val)


def timestamp_to_content(ts: datetime) -> tuple[date, time]:
    """Convert a timestamp into a date (in content days) and a time."""
    time_val = ts.time()
    day = ts.date()
    if time_val > time(0) and time_val < CONTENT_DAY_START:
        day -= timedelta(days=1)
    return day, time_val


def availability_time_ranges(type: ScheduleItemType) -> list[tuple[time, time]]:
    """Time ranges which proposers can select for their availability when they finalise talks.

    Changing these mid-event is probably inadvisable.
    """
    if type == "performance":
        time_ranges = [(time(14), time(18)), (time(18), time(22)), (time(22), time(2))]
    else:
        time_ranges = [(time(10), time(13)), (time(13), time(18)), (time(18), time(22))]

    return time_ranges
