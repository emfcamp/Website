from ..event_date import edt

parking_shifts = {
    "Car Parking": {
        "Car Park": [
            {
                "first": edt(d, "08:00:00"),
                "final": edt(d, "20:00:00"),
                "min": 1,
                "max": 3,
            } for d in ["thur", "fri"]
        ] + [
            {
                "first": edt(d, "10:00:00"),
                "final": edt(d, "16:00:00"),
                "min": 1,
                "max": 1,
            } for d in ["sat", "sun"]
        ] + [
            {
                "first": edt("mon", "08:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 1,
                "max": 1,
            },
        ]
    },
}
