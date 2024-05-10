from ..event_date import edt

arcade_shifts = {
    "Arcade Assistant": {
        "Arcade": [
            {
                "first": edt("fri", "10:00:00"),
                "final": edt("fri", "18:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sat", "18:00:00"),
                "min": 1,
                "max": 3,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("sun", "18:00:00"),
                "min": 1,
                "max": 3,
            },
        ]
    }
}
