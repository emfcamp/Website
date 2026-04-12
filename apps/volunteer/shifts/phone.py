from ..event_date import edt

phone_shifts = {
    "phone-helpdesk-assistant": {
        "phone-tent": [
            {
                "first": edt(d, "09:00:00"),
                "final": edt(d, "18:00:00"),
                "min": 1,
                "max": 1,
                "base_duration": 180,
            }
            for d in ["fri", "sat", "sun"]
        ]
    }
}
