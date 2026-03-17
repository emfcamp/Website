from datetime import timedelta

from models import config_date

event_days = {"wed": 0, "weds": 0, "thu": 1, "thur": 1, "thurs": 1, "fri": 2, "sat": 3, "sun": 4, "mon": 5}


def edt(day, time):
    if isinstance(day, str):
        day = event_days[day.lower()]
    # EVENT_START is day 1
    day0 = config_date("EVENT_START").date() - timedelta(days=1)
    # We make assumptions that day 0 is a weds - so check
    assert day0.weekday() == 2, "day0 is not a wednesday"
    delta = timedelta(days=day)
    return f"{(day0 + delta).strftime('%Y-%m-%d')} {time}"
