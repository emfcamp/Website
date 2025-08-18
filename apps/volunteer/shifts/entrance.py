from ..event_date import edt

entrance_shifts = {
    "Entrance Steward": {
        "Entrance Tent": [
            {
                "first": edt("thur", "09:00:00"),
                "final": edt("thur", "11:00:00"),
                "min": 3,
                "max": 5,
            },
            {
                "first": edt("thur", "11:00:00"),
                "final": edt("thur", "17:00:00"),
                "min": 5,
                "max": 7,
            },
            {
                "first": edt("thur", "17:00:00"),
                "final": edt("thur", "19:00:00"),
                "min": 2,
                "max": 3,
            },
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "19:00:00"),
                "min": 2,
                "max": 4,
            },
        ]
        + [
            {
                "first": edt(d, "19:00:00"),
                "final": edt(d, "23:00:00"),
                "min": 1,
                "max": 2,
            }
            for d in ["thur", "fri"]
        ]
        + [
            {
                "first": edt(d, "09:00:00"),
                "final": edt(d, "21:00:00"),
                "min": 1,
                "max": 2,
            }
            for d in ["sat", "sun"]
        ]
    },
}
