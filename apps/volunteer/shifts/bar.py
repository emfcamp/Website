from ..event_date import edt

bar_shifts = {
    "Bar": {
        "Bar": [
            {
                "first": edt("thur", "15:00:00"),
                "final": edt("fri", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 10,
            },
            {
                "first": edt("thur", "16:00:00"),
                "final": edt("fri", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 10,
            },
            {
                "first": edt("fri", "11:00:00"),
                "final": edt("sat", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 10,
            },
            {
                "first": edt("fri", "12:00:00"),
                "final": edt("sat", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 10,
            },
            {
                "first": edt("sat", "11:00:00"),
                "final": edt("sun", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 10,
            },
            {
                "first": edt("sat", "12:00:00"),
                "final": edt("sun", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 10,
            },
            {
                "first": edt("sun", "11:00:00"),
                "final": edt("mon", "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 10,
            },
            {
                "first": edt("sun", "12:00:00"),
                "final": edt("mon", "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 10,
            },
        ]
    },
    "Cybar": {
        "Cybar": [
            {
                "first": edt("fri", "20:00:00"),
                "final": edt("fri", "22:00:00"),
                "min": 1,
                "max": 2,
                "changeover": 10,
            },
            {
                "first": edt("fri", "22:00:00"),
                "final": edt("sat", "01:00:00"),
                "min": 1,
                "max": 2,
                "base_duration": 90,
                "changeover": 10,
            },
            {
                "first": edt("sat", "13:00:00"),
                "final": edt("sun", "01:00:00"),
                "min": 1,
                "max": 2,
                "changeover": 10,
            },
            {
                "first": edt("sun", "13:00:00"),
                "final": edt("mon", "01:00:00"),
                "min": 1,
                "max": 2,
                "changeover": 10,
            },
        ]
    },

 }
