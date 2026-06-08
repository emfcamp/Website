from ..event_date import edt

entrance_shifts = {
    "entrance-steward": {
        "live-in-vehicle-checkin": [
            {
                "first": edt(0, "12:00:00"),
                "final": edt(0, "18:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt(1, "08:00:00"),
                "final": edt(1, "18:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt(2, "08:00:00"),
                "final": edt(2, "18:00:00"),
                "min": 2,
                "max": 2,
            },
        ],
        "entrance-tent": [
            {
                "note": "A shift",
                "first": edt(1, "08:00:00"),
                "final": edt(1, "16:00:00"),
                "min": 3,
                "max": 3,
            },
            {
                "note": "B shift",
                "first": edt(1, "09:00:00"),
                "final": edt(1, "17:00:00"),
                "min": 3,
                "max": 3,
            },
            {
                "note": "Evening shift",
                "first": edt(1, "17:00:00"),
                "final": edt(2, "03:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "note": "A shift",
                "first": edt(2, "08:00:00"),
                "final": edt(2, "16:00:00"),
                "min": 3,
                "max": 3,
            },
            {
                "note": "B shift",
                "first": edt(2, "09:00:00"),
                "final": edt(2, "17:00:00"),
                "min": 3,
                "max": 3,
            },
            {
                "note": "Evening shift",
                "first": edt(2, "17:00:00"),
                "final": edt(3, "03:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "note": "A shift",
                "first": edt(3, "08:00:00"),
                "final": edt(3, "16:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "note": "B shift",
                "first": edt(3, "09:00:00"),
                "final": edt(3, "15:00:00"),
                "min": 3,
                "max": 3,
            },
            {
                "note": "Evening shift",
                "first": edt(3, "16:00:00"),
                "final": edt(4, "00:00:00"),
                "min": 2,
                "max": 2,
            },
            {
                "first": edt(4, "08:00:00"),
                "final": edt(5, "00:00:00"),
                "min": 2,
                "max": 2,
            },
        ],
    },
}
