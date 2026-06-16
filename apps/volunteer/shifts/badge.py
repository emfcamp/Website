from ..event_date import edt

badge_shifts = {
    "badge-helper": {
        "badge-tent": [
            {
                "first": edt(d, "10:00:00"),
                "final": edt(d, "18:00:00"),
                "min": 2,
                "max": 4,
            }
            for d in ["fri", "sat", "sun"]
        ]
    },
}
