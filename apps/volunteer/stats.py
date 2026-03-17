from collections import defaultdict

from flask import jsonify

from models.volunteer.shift import Shift
from models.volunteer.volunteer import Volunteer

from . import volunteer


@volunteer.route("/shifts.json")
def shifts():
    shifts = Shift.get_all()
    return jsonify(
        [
            {
                "role": s.role.name,
                "venue": s.venue.name,
                "start": s.start,
                "end": s.end,
                "min_needed": s.min_needed,
                "max_needed": s.max_needed,
                "signed_up": s.current_count,
            }
            for s in shifts
        ]
    )


@volunteer.route("/volunteer_histogram.json")
def vol_histogram():
    hist = defaultdict(lambda: 0)
    for v in Volunteer.get_all():
        hist[len(v.user.shift_entries)] += 1
    return jsonify(hist)
