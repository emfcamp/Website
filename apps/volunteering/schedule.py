from flask import (
    render_template, current_app as app
)
from flask_login import current_user

from ..common.forms import Form
from . import volunteering

from wtforms import (
    SelectMultipleField, BooleanField
)


ALL_SHIFTS = [
    {"time": "09", "day": "friday", "shifts": {"gate": 1, "stage-a": 2}},
    {"time": "10", "day": "friday", "shifts": {"gate": 3, "stage-a": 4, "stage-b": 5}},
    {"time": "11", "day": "friday", "shifts": {"gate": 6, "stage-a": 7, "stage-b": 8, "bar-1": 9}},
    {"time": "12", "day": "friday", "shifts": {"gate": 10, "stage-a": 11, "stage-b": 12, "bar-2": 13}}]

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


@volunteering.route('/schedule')
def schedule():
    # TODO redirect if not logged in
    form = ScheduleFilterForm()
    # TODO actually generate this list
    locations = ["bar-1", "bar-2", "gate", "stage-a", "stage-b", "stage-c"]
    return render_template('volunteering/schedule.html', locations=locations,
                            form=form, all_shifts=ALL_SHIFTS)


@volunteering.route('/shift/<id>')
def shift(id):
    return render_template('volunteering/shift.html', id=id)
