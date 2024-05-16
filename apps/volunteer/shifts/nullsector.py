from ..event_date import edt

nullsector_shifts = {
    "Null Sector Assistant": {
        "Null Sector": [
            {
                "first": edt("fri", "18:00:00"),
                "final": edt("sat", "00:00:00"),
                "min": 2,
                "max": 3,
            }
        ] + [
            {
                "first": edt(d[0], "12:00:00"),
                "final": edt(d[1], "00:00:00"),
                "min": 2,
                "max": 3,
            } for d in [("sat", "sun"), ("sun", "mon")]
        ]
    }
}
