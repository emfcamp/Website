from ..event_date import edt

vm_times = [
    {
        "first": edt("thur", "17:30:00"),
        "final": edt("thur", "22:30:00"),
        "min": 1,
        "max": 1,
        "base_duration": 300,
        "changeover": 0,
    },
] + [
    {
        "first": edt(d[0], "19:45:00"),
        "final": edt(d[1], "02:00:00"),
        "min": 1,
        "max": 1,
        "base_duration": 375,
        "changeover": 0,
    }
    for d in [("fri", "sat"), ("sat", "sun"), ("sun", "mon")]
]
tech_times = [
    {
        "first": edt("thur", "17:30:00"),
        "final": edt("thur", "22:30:00"),
        "min": 1,
        "max": 1,
        "base_duration": 150,
        "changeover": 15,
    },
] + [
    {
        "first": edt(d[0], "20:00:00"),
        "final": edt(d[1], "02:00:00"),
        "min": 1,
        "max": 1,
        "base_duration": 180,
        "changeover": 15,
    }
    for d in [("fri", "sat"), ("sat", "sun"), ("sun", "mon")]
]

bands_shifts = {
    "bands_artist_liason": {
        "Stage B": [
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
    "bands_venue_manager": {
        "Stage B": vm_times,
    },
    "bands_sound_operator": {"Stage B": tech_times},
    "bands_sound_technician": {"Stage B": tech_times},
    "bands_lighting_operator": {"Stage B": tech_times},
    "bands_stage_crew": {
        "Stage B": [
            {
                "first": edt(d, "20:00:00"),
                "final": edt(d, "23:00:00"),
                "min": 1,
                "max": 1,
                "base_duration": 90,
                "changeover": 15,
            }
            for d in ["fri", "sat", "sun"]
        ],
    },
}
