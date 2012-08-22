from main import db, app
from models.volunteers import ShiftSlot, Shift
from flask import render_template, request, redirect, url_for, flash
from flaskext.login import \
login_user, login_required, logout_user, current_user
from flaskext.wtf import Form, Required, \
SelectField, IntegerField, HiddenField, BooleanField, SubmitField, \
FieldList, FormField

def bool_cast(value):
    if type(value) == bool:
        return value
    elif value == None:
        return False
    elif type(value) == unicode:
        if value==u"True":
            return True
        elif value==u"False":
            return False
        else:
            raise TypeError("%s is not a valid unicode representation of a bool", val)
    else:
        raise TypeError("%s is not a valid unicode representation of a bool", val)

class HiddenIntegerField(HiddenField, IntegerField):
    """
    widget=HiddenInput() doesn't work with WTF-Flask's hidden_tag()
    """

class HiddenBooleanField(HiddenField, BooleanField):
    """
    widget=HiddenInput() doesn't work with WTF-Flask's hidden_tag()
    """

class ShiftForm(Form):
    shift_id   = HiddenIntegerField('Ticket Type', [Required()])
    # use the previous state to add/remove entries
    prev_state = HiddenBooleanField('Previous State', [Required()])
    work_shift = BooleanField('work_shift')

class ShiftsForm(Form):
    shifts = FieldList(FormField(ShiftForm))
    submit = SubmitField('Update shifts')

@app.route("/volunteers/shifts", methods=['GET', 'POST'])
def list_shifts():
    #
    # list all shifts
    # 	a user can pick shifts here
    # 	an admin can see who is on which shift
    #	understaffed shifts are highlighted
    #	immenient understaffed shifts are highlighted more.
    #
    if not current_user.is_authenticated():
        return redirect(url_for('signup', next=url_for('tickets_choose')))

    form = ShiftsForm(request.form)

    if not form.shifts:
        for ss in ShiftSlot.query.order_by(ShiftSlot.role_id, ShiftSlot.start_time).all():
            form.shifts.append_entry()
            form.shifts[-1].shift_id.data = ss.id
            form.shifts[-1]._type = ss
            
            if Shift.query.filter_by( \
                    user_id=current_user.id, \
                    shift_slot_id=ss.id, \
                    state='pending').count():
                 form.shifts[-1].prev_state.data = True
                 form.shifts[-1].work_shift.data = True
            else:
                 form.shifts[-1].prev_state.data = False
                 form.shifts[-1].work_shift.data = False
    else:
        for shift in form.shifts:
            # if shift.work_shift.data:
            shift._type = ShiftSlot.query.filter_by(id=shift.shift_id.data).one()
    
    # # TODO Make sure validate() works
    if request.method == "POST":
        for shift in form.shifts:
            prev    = bool_cast(shift.prev_state.data)
            current = bool_cast(shift.work_shift.data)
            
            if (prev != current) and (prev == False):
                if Shift.query.filter_by( \
                        user_id=current_user.id, \
                        shift_slot_id=shift.shift_id.data, \
                        state='cancelled').count():
                    app.logger.info('Updating shift %s', shift.shift_id.data)
                    mod_shift = current_user.shifts.filter_by( \
                        shift_slot_id=shift.shift_id.data, \
                        user_id=current_user.id).one()
                    mod_shift.state='pending'
                    db.session.add(mod_shift)
                else:
                    app.logger.info('Adding new shift %s', shift.shift_id.data)
                    new_shift = Shift(shift.shift_id.data, current_user.id)
                    current_user.shifts.append(new_shift)
                    db.session.add(current_user)
                
            elif (prev != current) and (prev == True):
                app.logger.info('Cancelling shift %s', shift.shift_id.data)
                mod_shift = current_user.shifts.filter_by( \
                    shift_slot_id=shift.shift_id.data, \
                    user_id=current_user.id, state='pending').one()
                mod_shift.state='cancelled'
                db.session.add(mod_shift)
                
            # update state info
            shift.prev_state.data = current
            # 

        db.session.commit()
        return redirect(url_for('my_shifts'))
    
    return render_template('volunteer_shifts.html', form=form)


@app.route("/volunteers/myshifts", methods=['GET'])
def my_shifts():
    #
    # list a users shifts and let them modify the shifts
    #
    if not current_user.is_authenticated():
        flash("You need to be logged in to sign up for volunteer shifts.")
        return redirect(url_for('login', next=url_for('my_shifts')))
        # select this users shifts
    all_shifts = Shift.query.filter_by(user_id=current_user.id).all()
    shifts = []
    
    for shift in all_shifts:
        shift_slot = ShiftSlot.query.filter_by(id=shift.shift_slot_id).one()
        shifts.append((shift, shift_slot))
        
    return render_template('volunteers/my_shifts.html', shifts=shifts)

