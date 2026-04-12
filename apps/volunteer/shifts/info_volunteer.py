from ..event_date import edt

info_vol_shifts = {
    "info-desk": {
        "info-volunteer-tent": [
            {
                "first": edt(d, "10:00:00"),
                "final": edt(d, "20:00:00"),
                "min": 1,
                "max": 3,
            }
            for d in ["thurs", "fri", "sat", "sun"]
        ]
        + [
            {
                "first": edt("mon", "10:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 1,
                "max": 3,
            },
        ]
    },
    "volunteer-manager": {
        "info-volunteer-tent": [
            {
                "first": edt(d, "09:00:00"),
                "final": edt(d, "21:00:00"),
                "min": 1,
                "max": 1,
            }
            for d in ["thurs", "fri", "sat", "sun"]
        ]
        + [
            {
                "first": edt("mon", "10:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 1,
                "max": 1,
            },
        ]
    },
    "volunteer-welfare": {
        "info-volunteer-tent": [
            {
                "first": edt(d, "09:00:00"),
                "final": edt(d, "21:00:00"),
                "min": 1,
                "max": 1,
            }
            for d in ["thurs", "fri", "sat", "sun"]
        ]
        + [
            {
                "first": edt("mon", "10:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 1,
                "max": 1,
            },
        ]
    },
    "cable-plugger": {
        "info-volunteer-tent": [
            {
                "first": edt(d, "10:00:00"),
                "final": edt(d, "20:00:00"),
                "min": 1,
                "max": 2,
            }
            for d in ["thurs", "fri", "sat", "sun"]
        ]
        + [
            {
                "first": edt("mon", "10:00:00"),
                "final": edt("mon", "12:00:00"),
                "min": 1,
                "max": 2,
            },
        ]
    },
}
