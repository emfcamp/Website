from ..event_date import edt

entrance_shifts = {
    "Entrance Steward": {
        "Entrance Tent": [
            {
                "first": edt(d, "09:00:00"),
                "final": edt(d, "23:00:00"),
                "min": 3,
                "max": 6,
            } for d in ["thur", "fri"]
        ] +
        [
            {
                "first": edt(d, "09:00:00"),
                "final": edt(d, "21:00:00"),
                "min": 1,
                "max": 2,
            } for d in ["sat", "sun"]
        ] +
        [
            {
                "first": edt("mon", "08:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 1,
                "max": 2,
            }
        ]
    },
}
