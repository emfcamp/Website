from flask import render_template
from collections import defaultdict

from ..common import feature_flag
from . import volunteer, v_user_required

from models.volunteer.shift import Shift


@volunteer.route('/schedule')
@feature_flag('VOLUNTEERS_SCHEDULE')
@v_user_required
def schedule():
    shifts = Shift.get_all()
    all_shifts = defaultdict(lambda: defaultdict(list))

    for s in shifts:
        day_key = s.start.strftime('%a').lower()
        hour_key = s.start.strftime('%H:%M')

        all_shifts[day_key][hour_key].append(s.to_dict())

    return render_template('volunteer/schedule.html', all_shifts=all_shifts)


@volunteer.route('/shift/<id>')
@feature_flag('VOLUNTEERS_SCHEDULE')
@v_user_required
def shift(id):
    return render_template('volunteer/shift.html', shift=Shift.query.get_or_404(id))

