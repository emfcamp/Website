from ..event_date improt edt

phone_shifts = {
    "Phone Helpdesk Assistant": {
        "Phone Team Tent": [
            {
                "first": edt(d, "09:00:00"),
                "final": edt(d, "18:00:00"),
                "min": 1,
                "max": 1,
                "base_duration": 180,
            } for d in ["fri", "sat", "sun"]
        ]
    }
}
