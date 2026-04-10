from ..event_date import edt

logistics_shifts = {
    "logistics-support": {
        "logistics-tent": [
            {
                "first": edt(d, "10:00:00"),
                "final": edt(d, "18:00:00"),
                "min": 2,
                "max": 4,
            }
            for d in ["wed", "thur", "fri", "sat", "sun"]
        ]
    },
    "vehicle-gate-escort": {
        "vehicle-gate-y": [
            {
                "first": edt(d, "09:00:00"),
                "final": edt(d, "19:00:00"),
                "min": 2,
                "max": 4,
            }
            for d in ["wed", "thur", "fri", "sat", "sun"]
        ]
        + [
            {
                "first": edt("mon", "08:00:00"),
                "final": edt("mon", "14:00:00"),
                "min": 2,
                "max": 4,
            }
        ]
    },
}
