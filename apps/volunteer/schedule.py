# coding=utf-8
from flask import (
    render_template, request, redirect, url_for, flash
)
from collections import defaultdict
from flask_login import current_user

from main import db

from models.volunteer.role import Role
from models.volunteer.shift import Shift, ShiftEntry

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

        s = s.to_dict()
        s['sign_up_url'] = url_for('.shift', shift_id=s['id'])

        by_time[day_key][hour_key].append(s)

    roles = [r.to_dict() for r in Role.get_all()]
    return render_template('volunteer/schedule.html', roles=roles, all_shifts=by_time,
                           active_day=request.args.get('day', default='fri'))


@volunteer.route('/shift/<shift_id>', methods=['GET', 'POST'])
@feature_flag('VOLUNTEERS_SCHEDULE')
@v_user_required
def shift(shift_id):
    shift = Shift.query.get_or_404(shift_id)

    if request.method == 'POST':
        shift_entry = ShiftEntry.query.filter_by(user_id=current_user.id, shift_id=shift_id).first()

        if shift_entry:
            db.session.delete(shift_entry)
            flash('Cancelled %s shift' % shift.role.name)
        else:
            current_user.shift_entries.append(ShiftEntry(user=current_user, shift=shift))
            flash('Signed up for %s shift' % shift.role.name)

        db.session.commit()
        return redirect(url_for('.schedule'))

    return render_template('volunteer/shift.html', shift=shift)


