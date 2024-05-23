from ..event_date import edt

stage_a_pattern = [
    {"first": edt("fri", "09:30:00"),
     "final": edt("fri", "11:30:00"),
     "min": 1,
     "max": 1,
     "changeover": 0
     },
    {"first": edt("fri", "11:30:00"),
     "final": edt("fri", "13:00:00"),
     "min": 1,
     "max": 1,
     "base_duration": 90
     },
    {"first": edt("fri", "13:00:00"),
     "final": edt("fri", "21:00:00"),
     "min": 1,
     "max": 1,
     },
    {"first": edt("sat", "10:00:00"),
     "final": edt("sat", "18:00:00"),
     "min": 1,
     "max": 1,
     },
    {"first": edt("sat", "18:00:00"),
     "final": edt("sat", "20:30:00"),
     "min": 1,
     "max": 1,
     "base_duration": 150
    },
    {"first": edt("sun", "10:00:00"),
     "final": edt("sun", "18:00:00"),
     "min": 1,
     "max": 1,
    },
    {"first": edt("sun", "18:00:00"),
     "final": edt("sun", "19:30:00"),
     "min": 1,
     "max": 1,
     "base_duration": 90
    }
]
stage_a_herald_vm = [
    {"first": edt("fri", "11:00:00"),
     "final": edt("fri", "21:00:00"),
     "min": 1,
     "max": 1,
     },
    {"first": edt("sat", "10:00:00"),
     "final": edt("sat", "18:00:00"),
     "min": 1,
     "max": 1,
     },
    {"first": edt("sat", "18:00:00"),
     "final": edt("sat", "20:30:00"),
     "min": 1,
     "max": 1,
     "base_duration": 150
    },
    {"first": edt("sun", "10:00:00"),
     "final": edt("sun", "16:00:00"),
     "min": 1,
     "max": 1,
    },
    {"first": edt("sun", "16:00:00"),
     "final": edt("sun", "19:00:00"),
     "min": 1,
     "max": 1,
     "base_duration": 180
    }
]

stage_bc_pattern = [
    {"first": edt("fri", "11:00:00"),
     "final": edt("fri", "17:00:00"),
     "min": 1,
     "max": 1,
    },
    {"first": edt("fri", "17:00:00"),
     "final": edt("fri", "20:00:00"),
     "min": 1,
     "max": 1,
     "base_duration": 90
    },
    {"first": edt("sat", "10:00:00"),
     "final": edt("sat", "20:00:00"),
     "min": 1,
     "max": 1,
    },
    {"first": edt("sun", "10:00:00"),
     "final": edt("sun", "16:00:00"),
     "min": 1,
     "max": 1,
    },
    {"first": edt("sun", "16:00:00"),
     "final": edt("sun", "18:30:00"),
     "min": 1,
     "max": 1,
     "base_duration": 180
    }
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
        "Stage A": stage_a_herald_vm,
        "Stage B": stage_bc_pattern,
        "Stage C": stage_bc_pattern,
    },
    "Talks: Camera Operator": {
        "Stage A": set_max(stage_a_pattern, 2),
        "Stage B": set_max(stage_bc_pattern, 2),
        "Stage C": set_max(stage_bc_pattern, 2),
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
        "Stage A": stage_a_herald_vm,
        "Stage B": stage_bc_pattern,
        "Stage C": stage_bc_pattern,
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
