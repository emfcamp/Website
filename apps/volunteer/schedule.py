# coding=utf-8
from flask import (
    render_template, request, redirect, url_for, flash, jsonify
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

        to_add = s.to_dict()
        to_add['sign_up_url'] = url_for('.shift', shift_id=to_add['id'])
        to_add['is_user_shift'] = current_user in s.volunteers

        by_time[day_key][hour_key].append(to_add)

    roles = [r.to_dict() for r in Role.get_all()]
    return render_template('volunteer/schedule.html', roles=roles, all_shifts=by_time,
                           active_day=request.args.get('day', default='fri'))

def _toggle_shift_entry(user, shift):
    res = {}
    shift_entry = ShiftEntry.query.filter_by(user_id=user.id, shift_id=shift.id).first()

    if shift_entry:
        db.session.delete(shift_entry)
        res['operation'] = 'delete'
        res['message'] = 'Cancelled %s shift' % shift.role.name
    else:
        for v_shift in user.shift_entries:
            if shift.is_clash(v_shift.shift):
                res['warning'] = "WARNING: Clashes with an existing shift"

        shift.entries.append(ShiftEntry(user=user, shift=shift))
        res['operation'] = 'add'
        res['message'] = 'Signed up for %s shift' % shift.role.name

    return res

@volunteer.route('/shift/<shift_id>', methods=['GET', 'POST'])
@feature_flag('VOLUNTEERS_SCHEDULE')
@v_user_required
def shift(shift_id):
    shift = Shift.query.get_or_404(shift_id)

    if request.method == 'POST':
        msg = _toggle_shift_entry(current_user, shift)

        db.session.commit()
        flash(msg['message'])
        return redirect(url_for('.schedule'))

    return render_template('volunteer/shift.html', shift=shift)


@volunteer.route('/shift/<shift_id>.json', methods=['GET', 'POST'])
@feature_flag('VOLUNTEERS_SCHEDULE')
@v_user_required
def shift_json(shift_id):
    shift = Shift.query.get_or_404(shift_id)

    if request.method == 'POST':
        msg = _toggle_shift_entry(current_user, shift)

        db.session.commit()
        return jsonify(msg)

    return jsonify(shift)


