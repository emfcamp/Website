from ..event_date import edt

bands_shifts = {
    "bands-artist-liason": {
        "stage-d": [
            {
                "first": edt("thur", "17:30:00"),
                "final": edt("thur", "23:00:00"),
                "min": 1,
                "max": 1,
                "base_duration": 330,
                "changeover": 0,
            },
            {
                "first": edt("fri", "17:30:00"),
                "final": edt("sat", "01:00:00"),
                "min": 1,
                "max": 1,
                "base_duration": 450,
                "changeover": 0,
            },
            {
                "first": edt("sat", "17:30:00"),
                "final": edt("sun", "01:00:00"),
                "min": 1,
                "max": 1,
                "base_duration": 450,
                "changeover": 0,
            },
            {
                "first": edt("sun", "17:30:00"),
                "final": edt("mon", "01:00:00"),
                "min": 1,
                "max": 1,
                "base_duration": 450,
                "changeover": 0,
            },
        ],
    },
}
