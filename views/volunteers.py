from main import app
from models.volunteers import ShiftSlot
from flask import render_template, request, redirect, url_for
from flaskext.login import current_user
from flaskext.wtf import Form, SelectField, StringField, Required, HiddenField

@app.route("/volunteers/shifts", methods=['GET', 'POST'])
def volunteers_shifts():
    slots = {31:{}, 1:{}, 2:{}}
    #
    # This currently shows the static information of the shifts
    # available and the roles needed
    # 
    for ss in ShiftSlot.query.order_by(ShiftSlot.start_time).all():
        
        if not ss.role.name in slots[ss.start_time.day]:
            slots[ss.start_time.day][ss.role.name] = [ss.start_time.hour,]
        else:
            slots[ss.start_time.day][ss.role.name].append(ss.start_time.hour)
        
    return render_template('volunteer_shifts.html', slots=slots)

@app.route("/volunteer/shifts", methods=['GET'])
def list_shifts():
    #
    # list all shifts
    # 	a user can pick shifts here
    # 	an admin can see who is on which shift
    #	understaffed shifts are highlighted
    #	immenient underdtaffed shifts are highlighted more.
    #
    if not urrent_user.is_authenticated():
        return redirect(url_for('main'))
    shifts = []
    return render_template('volunteers/list_shifts.html')

@app.route("/volunteer/myshifts", methods=['GET'])
def my_shifts():
    #
    # list a users shifts and let them modify the shifts
    #
    if not urrent_user.is_authenticated():
        return redirect(url_for('main'))
    # select this users shifts
    shifts = []
    return render_template('volunteers/my_shifts.html')