from flask import render_template
from wtforms import SelectMultipleField, BooleanField
from collections import defaultdict

from ..common import feature_flag
from ..common.forms import Form
from . import volunteer, v_user_required

from models.volunteer.shift import Shift

class ScheduleFilterForm(Form):
    trained_for = BooleanField("Only show roles I have training for")
    roles = SelectMultipleField("Filter by role", choices=[('bar', 'Bar'),
        ('gate', 'Gate'), ('stage', 'Stage'), ('kids', 'Youth')])
    location = SelectMultipleField("Filter by location",
                                   choices=[('bar-1', 'Bar'),
                                            ('bar-2', 'Bar (secret)'),
                                            ('gate', 'Gate'),
                                            ('stage-a', 'Stage A'),
                                            ('stage-b', 'Stage B'),
                                            ('stage-c', 'Stage C')])

@volunteer.route('/schedule')
@feature_flag('VOLUNTEERS_SCHEDULE')
@v_user_required
def schedule():
    # TODO redirect if not logged in
    form = ScheduleFilterForm()
    shifts = Shift.get_all()
    all_shifts = defaultdict(lambda: defaultdict(list))

    for s in shifts:
        day_key = s.start.strftime('%a').lower()
        hour_key = s.start.strftime('%H:%M')

        all_shifts[day_key][hour_key].append(s)

    return render_template('volunteer/schedule.html', form=form, all_shifts=all_shifts)

@volunteer.route('/shift/<id>')
@feature_flag('VOLUNTEERS_SCHEDULE')
@v_user_required
def shift(id):
    return render_template('volunteer/shift.html', shift=Shift.query.get_or_404(id))

