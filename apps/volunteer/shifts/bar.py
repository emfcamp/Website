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
            }
        ] + [
            {
                "first": edt(d[0], "11:00:00"),
                "final": edt(d[1], "01:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 10,
            } for d in [("fri", "sat"), ("sat", "sun"), ("sun", "mon")]
        ] + [
            {
                "first": edt(d[0], "12:00:00"),
                "final": edt(d[1], "00:00:00"),
                "min": 1,
                "max": 3,
                "changeover": 10,
            } for d in [("fri", "sat"), ("sat", "sun"), ("sun", "mon")]
        ]
    },
    "Cybar": {
        "Cybar": [
            {
                "first": edt("fri", "18:00:00"),
                "final": edt("sat", "02:00:00"),
                "min": 1,
                "max": 2,
                "changeover": 10,
            },
            {
                "first": edt("sat", "10:00:00"),
                "final": edt("sun", "02:00:00"),
                "min": 1,
                "max": 2,
                "changeover": 10,
            },
            {
                "first": edt("sun", "10:00:00"),
                "final": edt("mon", "02:00:00"),
                "min": 1,
                "max": 2,
                "changeover": 10,
            },
        ]
    },

 }
