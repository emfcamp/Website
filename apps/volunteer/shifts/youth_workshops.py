from ..event_date import edt

youth_workshop_shifts = {
    "Youth Workshop Helper": {
        "Youth Workshop": [
            {"first": edt(t[0], t[1]), "final": edt(t[0], t[2]), "min": 2, "max": 2, "base_duration": t[3]}
            for t in [
                ("fri", "14:00:00", "15:00:00", 60),
                ("fri", "15:30:00", "16:30:00", 60),
                ("fri", "18:30:00", "20:00:00", 90),
                ("sat", "11:00:00", "12:30:00", 90),
                ("sat", "13:00:00", "14:30:00", 90),
                ("sat", "17:50:00", "19:20:00", 90),
                ("sun", "16:00:00", "17:00:00", 60),
            ]
        ]
    }
}
