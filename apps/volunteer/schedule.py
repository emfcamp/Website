# coding=utf-8
from flask import (
    render_template, request, redirect, url_for, flash, jsonify
)
from collections import defaultdict
from flask_login import current_user
from flask import Markup
import markdown
from glob import glob

from main import db

from models.volunteer.role import Role
from models.volunteer.shift import Shift, ShiftEntry
from models.volunteer.volunteer import Volunteer

from ..common import feature_flag
from . import volunteer, v_user_required


def _get_interested_roles(user):
    roles = Role.get_all()
    volunteer = Volunteer.get_for_user(user)
    res = []

    for r in roles:
        to_add = r.to_dict()
        to_add['is_interested'] = (r in volunteer.interested_roles)
        to_add['is_trained'] = (r in volunteer.trained_roles)

        res.append(to_add)

    return res

@volunteer.route('/schedule')
@feature_flag('VOLUNTEERS_SCHEDULE')
@v_user_required
def schedule():
    shifts = Shift.get_all()
    by_time = defaultdict(lambda: defaultdict(list))

    for s in shifts:
        day_key = s.start.strftime('%a').lower()
        hour_key = s.start.strftime('%H:%M')

        to_add = s.to_localtime_dict()
        to_add['sign_up_url'] = url_for('.shift', shift_id=to_add['id'])
        to_add['is_user_shift'] = current_user in s.volunteers

        by_time[day_key][hour_key].append(to_add)

    roles = _get_interested_roles(current_user)
    role_descriptions = _format_role_descriptions()

    untrained_roles = [r for r in roles if r['requires_training'] and not r['is_trained']]

    return render_template('volunteer/schedule.html', roles=roles, all_shifts=by_time,
                           active_day=request.args.get('day', default='fri'),
                           role_descriptions=role_descriptions, untrained_roles=untrained_roles)

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

def _format_role_descriptions():
    roles = {}
    extensions = ["markdown.extensions.nl2br"]

    for name in glob('apps/volunteer/role_descriptions/*.md'):
        role_id = name.split('/')[-1].replace('.md', '')
        content = open(name, "r").read()
        roles[role_id] = Markup(markdown.markdown(content, extensions=extensions))

    return roles

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


