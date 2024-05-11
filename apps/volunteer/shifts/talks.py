from ..event_date import edt

herald_pattern = [
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "21:00:00"),
                "min": 1,
                "max": 1,
            } for d in ["fri", "sat", "sun"]
        ]
stage_pattern = [
    {"first": edt(d, "10:00:00"),
     "final": edt(d, "18:00:00"),
     "min": 1,
     "max": 1,
    } for d in ["fri", "sat", "sun"]
]
vm_pattern = [
    {"first": edt(d, "10:00:00"),
     "final": edt(d, "18:00:00"),
     "min": 1,
     "max": 1,
     "base_duration": 240
    } for d in ["fri", "sat", "sun"]
]

talks_shifts = {
    "Green Room Runner": {
        "Green Room": [
            {
                "first": edt(d, "09:00:00"),
                "final": edt(d, "21:00:00"),
                "min": 1,
                "max": 2,
            } for d in ["fri", "sat", "sun"]
        ]
    },
    "Content Team": {
      "Green Room": [
            {
                "first": edt(d, "09:00:00"),
                "final": edt(d, "21:00:00"),
                "min": 1,
                "max": 1,
            } for d in ["fri", "sat", "sun"]
        ]
    },
    "Herald": {
        "Stage A": herald_pattern,
        "Stage B": herald_pattern,
        "Stage C": herald_pattern,
    },
    "Talks: Camera Operator": {
        "Stage A": stage_pattern,
        "Stage B": stage_pattern,
        "Stage C": stage_pattern,
    },
    "Talks: Vision Mixer": {
        "Stage A": stage_pattern,
        "Stage B": stage_pattern,
        "Stage C": stage_pattern,
    },
    "Talks: Sound/Lighting Operator": {
        "Stage A": stage_pattern,
        "Stage B": stage_pattern,
        "Stage C": stage_pattern,
    },
    "Talks: Venue Manager": {
        "Stage A": vm_pattern,
        "Stage B": vm_pattern,
        "Stage C": vm_pattern,
    },
    "Video Editor": {
        "VOC": [
            {
                "first": edt(d, "10:00:00"),
                "final": edt(d, "18:00:00"),
                "min": 0,
                "max": 5,
            } for d in ["fri", "sat", "sun"]
        ]
    }
}
