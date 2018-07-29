from flask import render_template
from wtforms import SelectMultipleField, BooleanField
from pendulum import period

from ..common.forms import Form
from . import volunteer

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
def schedule():
    # TODO redirect if not logged in
    form = ScheduleFilterForm()
    shifts = Shift.get_all()
    venues = sorted(set([s.venue for s in shifts]), key=lambda v: v.name)
    # times = sorted(set([s.start for s in shifts]))
    start = min(shifts, key=lambda s: s.start).start
    end = max(shifts, key=lambda s: s.end).end
    times = [t.strftime('%a %H:%M') for t in period(start, end).range('minutes', 15)]
    all_shifts = {}

    for s in shifts:
        t = all_shifts.get(s.start.strftime('%a %H:%M'), {})

        t[s.venue_id] = s
        all_shifts[s.start.strftime('%a %H:%M')] = t

    return render_template('volunteer/schedule.html', form=form,
                            venues=venues, times=times, all_shifts=all_shifts)

@volunteer.route('/shift/<id>')
def shift(id):
    return render_template('volunteer/shift.html', shift=Shift.query.get_or_404(id))

