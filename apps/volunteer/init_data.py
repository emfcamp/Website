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


shift_list: dict[str, dict[str, dict[str, Any]]] = {
from datetime import datetime, timedelta
event_days = {
    "wed": 0, "weds":0,
    "thur": 1, "thurs": 1,
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
        "Vehicle Gate Y": [
            {
                "first": edt("wed", "11:00:00"),
                "final": edt("wed", "23:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "15:00:00"),
                "final": edt("sat", "23:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sun", "08:00:00"),
                "final": edt("sun", "12:00:00"),
                "min": 1,
                "max": 1,
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
    "Info Desk": {
        "Info/Volunteer Tent": [
            {
                "first": edt("wed", "10:00:00"),
                "final": edt("wed", "20:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("thu", "10:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "12:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Volunteer Manager": {
        "Info/Volunteer Tent": [
            {
                "first": edt("wed", "09:00:00"),
                "final": edt("wed", "21:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("thu", "09:00:00"),
                "final": edt("thu", "21:00:00"),
                "min": 1,
                "max": 2,
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
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "12:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Youth Workshop Helper": {
        "Youth Workshop": [
            {
                "first": edt("thu", "11:00:00"),
                "final": edt("thu", "17:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("thu", "17:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 2,
                "base_duration": 90,
            },
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "15:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("fri", "15:00:00"),
                "final": edt("fri", "19:30:00"),
                "min": 1,
                "max": 2,
                "base_duration": 90,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "19:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Bar": {
        "Bar": [
            {
                "first": edt("wed", "11:00:00"),
                "final": edt("thu", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("wed", "12:00:00"),
                "final": edt("thu", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("thu", "11:00:00"),
                "final": edt("fri", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("thu", "12:00:00"),
                "final": edt("fri", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("fri", "11:00:00"),
                "final": edt("sat", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("sat", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("sat", "11:00:00"),
                "final": edt("sun", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
            {
                "first": edt("sat", "12:00:00"),
                "final": edt("sun", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 0,
            },
        ]
    },
    "Cybar": {
        "Cybar": [
            {
                "first": edt("thu", "20:00:00"),
                "final": edt("thu", "22:00:00"),
                "min": 1,
                "max": 2,
                "changeover": 0,
            },
            {
                "first": edt("thu", "22:00:00"),
                "final": edt("fri", "01:00:00"),
                "min": 1,
                "max": 2,
                "base_duration": 90,
            },
            {
                "first": edt("fri", "13:00:00"),
                "final": edt("sat", "01:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "13:00:00"),
                "final": edt("sun", "01:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "NOC Helper": {
        "NOC": [
            {
                "first": edt("wed", "10:00:00"),
                "final": edt("wed", "20:00:00"),
                "min": 1,
                "max": 2,
                # "base_duration": 90,
            },
            {
                "first": edt("thu", "10:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 2,
                # "base_duration": 90,
            },
            {
                "first": edt("sat", "12:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 2,
                # "base_duration": 90,
            },
            {
                "first": edt("sun", "08:00:00"),
                "final": edt("sun", "12:00:00"),
                "min": 1,
                "max": 2,
                # "base_duration": 90,
            },
        ]
    },
    "Herald": {
        "Stage A": [
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
        ],
        "Stage B": [
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
        ],
        "Stage C": [
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
        ],
    },
    "Stage: Audio/Visual": {
        "Stage A": [
            {
                "first": edt("thu", "12:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage B": [
            {
                "first": edt("thu", "12:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage C": [
            {
                "first": edt("thu", "12:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
    },
    "Stage: Camera Operator": {
        "Stage A": [
            {
                "first": edt("thu", "12:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage B": [
            {
                "first": edt("thu", "12:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage C": [
            {
                "first": edt("thu", "12:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
    },
    "Stage: Vision Mixer": {
        "Stage A": [
            {
                "first": edt("thu", "12:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage B": [
            {
                "first": edt("thu", "12:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
        "Stage C": [
            {
                "first": edt("thu", "12:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 1,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 1,
            },
        ],
    },
    "Kitchen Helper": {
        "Volunteer Kitchen": [
            {
                "first": edt("wed", "06:00:00"),
                "final": edt("wed", "22:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("thu", "06:00:00"),
                "final": edt("thu", "22:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("fri", "06:00:00"),
                "final": edt("fri", "22:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("sat", "06:00:00"),
                "final": edt("sat", "22:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("sun", "06:00:00"),
                "final": edt("sun", "12:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("wed", "09:00:00"),
                "final": edt("wed", "11:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("wed", "13:00:00"),
                "final": edt("wed", "15:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("wed", "19:30:00"),
                "final": edt("wed", "21:30:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("thu", "09:00:00"),
                "final": edt("thu", "11:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("thu", "13:00:00"),
                "final": edt("thu", "15:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("thu", "19:30:00"),
                "final": edt("thu", "21:30:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "11:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("fri", "13:00:00"),
                "final": edt("fri", "15:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("fri", "19:30:00"),
                "final": edt("fri", "21:30:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "11:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("sat", "13:00:00"),
                "final": edt("sat", "15:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("sat", "19:30:00"),
                "final": edt("sat", "21:30:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "11:00:00"),
                "min": 2,
                "max": 2,
            },
        ]
    },
    "Runner": {
        "Info/Volunteer Tent": [
            {
                "first": edt("wed", "09:30:00"),
                "final": edt("wed", "23:30:00"),
                "min": 3,
                "max": 6,
            },
            {
                "first": edt("thu", "10:00:00"),
                "final": edt("thu", "20:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "20:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "20:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("sun", "08:00:00"),
                "final": edt("sun", "12:00:00"),
                "min": 3,
                "max": 6,
            },
        ]
    },
    "Logistics Support": {
        "Logistics Tent": [
            {
                "first": edt("wed", "11:00:00"),
                "final": edt("wed", "17:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("thu", "09:00:00"),
                "final": edt("thu", "17:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "17:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "17:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "11:00:00"),
                "min": 1,
                "max": 3,
                # "base_duration": 90,
            },
            {
                "first": edt("sun", "11:00:00"),
                "final": edt("sun", "12:30:00"),
                "min": 1,
                "max": 3,
                "base_duration": 90,
            },
        ]
    },
    "Tent Team Helper": {
        "N/A": [
            {
                "first": edt("wed", "17:00:00"),
                "final": edt("wed", "19:00:00"),
                "min": 1,
                "max": 4,
            },
            {
                "first": edt("thu", "17:00:00"),
                "final": edt("thu", "19:00:00"),
                "min": 1,
                "max": 4,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "12:30:00"),
                "min": 1,
                "max": 4,
            },
        ]
    },
    "Shop Helper": {
        "Shop": [
            {
                "first": edt("wed", "10:00:00"),
                "final": edt("wed", "18:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("thu", "10:00:00"),
                "final": edt("thu", "18:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "18:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "18:00:00"),
                "min": 2,
                "max": 3,
            },
        ]
    },
    "Music: Stage Hand": {
        "Stage B": [
            {
                "first": edt("wed", "19:00:00"),
                "final": edt("wed", "21:00:00"),
                "min": 2,
                "max": 4,
            },
            {
                "first": edt("wed", "21:00:00"),
                "final": edt("wed", "22:30:00"),
                "min": 2,
                "max": 4,
                "base_duration": 90,
            },
            {
                "first": edt("thu", "18:00:00"),
                "final": edt("fri", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("fri", "18:00:00"),
                "final": edt("sat", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "18:00:00"),
                "final": edt("sun", "00:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Music: Lighting Operator": {
        "Stage B": [
            {
                "first": edt("wed", "19:00:00"),
                "final": edt("wed", "21:00:00"),
                "min": 2,
                "max": 4,
            },
            {
                "first": edt("wed", "21:00:00"),
                "final": edt("wed", "22:30:00"),
                "min": 2,
                "max": 4,
                "base_duration": 90,
            },
            {
                "first": edt("thu", "18:00:00"),
                "final": edt("fri", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("fri", "18:00:00"),
                "final": edt("sat", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "18:00:00"),
                "final": edt("sun", "00:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Music: Sound Engineer": {
        "Stage B": [
            {
                "first": edt("wed", "19:00:00"),
                "final": edt("wed", "21:00:00"),
                "min": 2,
                "max": 4,
            },
            {
                "first": edt("wed", "21:00:00"),
                "final": edt("wed", "22:30:00"),
                "min": 2,
                "max": 4,
                "base_duration": 90,
            },
            {
                "first": edt("thu", "18:00:00"),
                "final": edt("fri", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("fri", "18:00:00"),
                "final": edt("sat", "02:00:00"),
                "min": 1,
                "max": 2,
            },
            {
                "first": edt("sat", "18:00:00"),
                "final": edt("sun", "00:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
    "Support Team": {
        "N/A": [
            {
                "first": edt("wed", "10:00:00"),
                "final": edt("wed", "22:00:00"),
                "min": 2,
                "max": 6,
            },
            {
                "first": edt("thu", "09:00:00"),
                "final": edt("thu", "19:00:00"),
                "min": 2,
                "max": 6,
            },
            {
                "first": edt("thu", "19:00:00"),
                "final": edt("thu", "22:00:00"),
                "min": 2,
                "max": 6,
                "base_duration": 90,
            },
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "19:00:00"),
                "min": 2,
                "max": 6,
            },
            {
                "first": edt("fri", "19:00:00"),
                "final": edt("fri", "22:00:00"),
                "min": 2,
                "max": 6,
                "base_duration": 90,
            },
            {
                "first": edt("sat", "09:00:00"),
                "final": edt("sat", "19:00:00"),
                "min": 2,
                "max": 6,
            },
            {
                "first": edt("sat", "19:00:00"),
                "final": edt("sat", "22:00:00"),
                "min": 2,
                "max": 6,
                "base_duration": 90,
            },
            {
                "first": edt("sun", "09:00:00"),
                "final": edt("sun", "12:00:00"),
                "min": 2,
                "max": 6,
                "base_duration": 90,
            },
        ]
    },
}

if __name__=="__main__":
    import pprint
    pprint.pp(shift_list)
