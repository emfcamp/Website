from ..event_date import edt

logistics_shifts = {
    "Logistics Support": {
        "Logistics Tent": [
            {
                "first": edt(d, "10:00:00"),
                "final": edt(d, "18:00:00"),
                "min": 2,
                "max": 4,
            } for d in ["wed", "thur", "fri", "sat", "sun"]]
    },
}
