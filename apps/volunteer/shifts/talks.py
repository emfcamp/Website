from ..event_date import edt

herald_pattern = [
            {
                "first": edt("fri", "09:00:00"),
                "final": edt("fri", "21:00:00"),
                "min": 1,
                "max": 1,
            } for d in ["fri", "sat", "sun"]
        ]

stage_a_pattern = [
    {"first": edt(d, "09:45:00"),
     "final": edt(d, "12:00:00"),
     "min": 1,
     "max": 1,
     "base_duration": 135
    } for d in ["fri", "sat"]
] +[
    {"first": edt(d, "12:00:00"),
     "final": edt(d, "20:00:00"),
     "min": 1,
     "max": 1,
    } for d in ["fri", "sat"]
] + [
    {"first": edt("sat", "09:45:00"),
     "final": edt("sat", "12:00:00"),
     "min": 1,
     "max": 1,
     "base_duration": 135
    },
    {"first": edt("sat", "12:00:00"),
     "final": edt("sat", "20:00:00"),
     "min": 1,
     "max": 1,
    },
    {"first": edt("sun", "09:45:00"),
     "final": edt("sun", "17:45:00"),
     "min": 1,
     "max": 1,
    },
    {"first": edt("sun", "17:45:00"),
     "final": edt("sun", "19:00:00"),
     "min": 1,
     "max": 1,
     "base_duration": 135
    }
]

stage_bc_pattern = [
    {"first": edt("fri", "10:45:00"),
     "final": edt("fri", "20:45:00"),
     "min": 1,
     "max": 1,
     "base_duration": 140
    },
    {"first": edt("fri", "17:45:00"),
     "final": edt("fri", "20:00:00"),
     "min": 1,
     "max": 1,
     "base_duration": 135
    },
    {"first": edt("sat", "09:45:00"),
     "final": edt("sat", "12:00:00"),
     "min": 1,
     "max": 1,
     "base_duration": 135
    },
    {"first": edt("sat", "12:00:00"),
     "final": edt("sat", "20:00:00"),
     "min": 1,
     "max": 1,
    },
    {"first": edt("sun", "09:45:00"),
     "final": edt("sun", "16:30:00"),
     "min": 1,
     "max": 1,
     "base_duration": 135
    },
    {"first": edt("sun", "16:30:00"),
     "final": edt("sun", "18:30:00"),
     "min": 1,
     "max": 1,
    }
]

vm_pattern = [
    {"first": edt(d, "10:00:00"),
     "final": edt(d, "20:30:00"),
     "min": 1,
     "max": 1,
     "base_duration": 315,
     "changeover": 30,
    } for d in ["fri", "sat", "sun"]
]

def set_max(shifts, val=2):
    return [s | {"max": val} for s in shifts]

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
        "Stage A": set_max(stage_a_pattern),
        "Stage B": set_max(stage_bc_pattern),
        "Stage C": set_max(stage_bc_pattern),
    },
    "Talks: Vision Mixer": {
        "Stage A": stage_a_pattern,
        "Stage B": stage_bc_pattern,
        "Stage C": stage_bc_pattern,
    },
    "Talks: Sound/Lighting Operator": {
        "Stage A": stage_a_pattern,
        "Stage B": stage_bc_pattern,
        "Stage C": stage_bc_pattern,
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
