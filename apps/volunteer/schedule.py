from flask import render_template, request, redirect, url_for, flash
from collections import defaultdict
from flask_login import current_user

from main import db

from models.volunteer.role import Role
from models.volunteer.shift import Shift

from ..common import feature_flag
from . import volunteer, v_user_required


@volunteer.route('/schedule')
@feature_flag('VOLUNTEERS_SCHEDULE')
@v_user_required
def schedule():
    shifts = Shift.get_all()
    by_time = defaultdict(lambda: defaultdict(list))

    for s in shifts:
        day_key = s.start.strftime('%a').lower()
        hour_key = s.start.strftime('%H:%M')

        by_time[day_key][hour_key].append(s.to_dict())

    roles = [r.to_dict() for r in Role.get_all()]
    return render_template('volunteer/schedule.html', roles=roles, all_shifts=by_time,
                           active_day=request.args.get('day', default='fri'))


@volunteer.route('/shift/<id>', methods=['GET', 'POST'])
@feature_flag('VOLUNTEERS_SCHEDULE')
@v_user_required
def shift(shift_id):
    shift = Shift.query.get_or_404(shift_id)

    if request.method == 'POST':
        if shift in current_user.shifts:
            current_user.shifts.remove(shift)
        else:
            current_user.shifts.add(shift)

        db.session.commit()
        flash('Signed up for %s shift' % shift.role.name)
        return redirect(url_for('.schedule'))

    return render_template('volunteer/shift.html', shift=shift)


