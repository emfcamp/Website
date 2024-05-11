from ..event_date import edt

arcade_shifts = {
    "Arcade Assistant": {
        "Arcade": [
            {
                "first": edt(d, "10:00:00"),
                "final": edt(d, "18:00:00"),
                "min": 1,
                "max": 3,
            } for d in ["fri", "sat", "sun"]
        ]
    }
}
