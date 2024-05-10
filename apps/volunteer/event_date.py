from datetime import datetime, timedelta

event_days = {
    "wed": 0, "weds":0,
    "thu": 1, "thur": 1, "thurs": 1,
    "fri": 2,
    "sat": 3,
    "sun": 4,
    "mon": 5
    }

def edt(day, time):
    fmt = "%Y-%m-%d"
    if isinstance(day, str):
        day = event_days[day.lower()]
    day0 = datetime.strptime("2024-05-29", fmt)
    #TODO: get date from config for that ^^
    delta = timedelta(days=day)
    return f"{(day0+delta).strftime(fmt)} {time}"
