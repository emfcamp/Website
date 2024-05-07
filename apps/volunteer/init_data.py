from pathlib import Path
from typing import Any

from flask import current_app as app
from yaml import safe_load


def load_from_yaml(path_glob: str) -> list[dict[str, Any]]:
    """Loads all YAML files from the passed path glob."""
    items = []

    for path in Path(app.root_path).glob(path_glob):
        with open(path, "r") as file:
            items.append(safe_load(file))

    return items


def load_initial_venues() -> list[dict[str, Any]]:
    """Loads venue data."""
    return load_from_yaml("apps/volunteer/data/venues/*.yml")


def load_initial_roles() -> list[dict[str, Any]]:
    """Loads role data."""
    return load_from_yaml("apps/volunteer/data/roles/*.yml")


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

    
shift_list: dict[str, dict[str, dict[str, Any]]] = {
    "Badge Helper": {
        "Badge Tent": [
            {
                "first": edt("thu", "10:00:00"),
                "final": edt("thu", "16:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "16:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "16:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Car Parking": {
        "Car Park": [
            {
                "first": edt("wed", "08:00:00"),
                "final": edt("wed", "20:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("thu", "08:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "16:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "16:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "08:00:00"),
                "final": edt("sun", "12:00:00"),
                "min": 1,
                "max": 1,
            },
        ]
    },
    "Entrance Steward": {
        "Entrance Tent": [
            {
                "first": edt("wed", "11:00:00"),
                "final": edt("wed", "23:00:00"),
                "min": 2,
                "max": 4,
            },
            {
                "first": edt("thu", "07:00:00"),
                "final": edt("thu", "23:00:00"),
                "min": 2,
                "max": 4,
            },
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "08:00:00"),
                "final": edt("sun", "12:00:00"),
                "min": 1,
                "max": 2,
            },
        ],
    },
    "Green Room Runner": {
        "Green Room": [
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "18:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Content Team": {
      "Green Room": [
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "21:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "21:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "18:00:00"),
                "min": 1,
                "max": 1,
            },
        ]
    },

}

if __name__=="__main__":
    import pprint
    pprint.pp(shift_list)
