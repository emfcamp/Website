from ..event_date import edt

shop_shifts = {
    "shop_helper": {
        "Shop": [
            {
                "first": edt(d, "10:00:00"),
                "final": edt(d, "16:00:00"),
                "min": 2,
                "max": 3,
            }
            for d in ["fri", "sat", "sun"]
        ]
    },
}
