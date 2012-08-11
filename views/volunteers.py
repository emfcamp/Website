from main import app
from models.volunteers import ShiftSlot
from flask import render_template, request, redirect, url_for
from flaskext.login import current_user
from flaskext.wtf import Form, SelectField, StringField, Required, HiddenField
# from users import NextURLField

# class HiddenStringField(HiddenField, StringField):
#     """String version of HiddenIntegerField"""
# 
# class StringSelectField(SelectField):
#     def __init__(seld, *args, **kwargs):
#         kwargs['coerce'] = str
#         self.fmt = kwargs.pop('fmt', str)
#         self.values = kwargs.pop('values', [])
#         SelectField.__init__(self, *args, **kwargs)
# 
#     @property
#     def values(self):
#         return self._values
# 
#     @values.setter
#     def values(self, vals):
#         self._values = vals
#         self.choices = [(i, self.fmt(i)) for i in vals]
#     
#     
# 
# 
# class ShiftSelectField(Form):
#     role_id = HiddenStringField('role type', [Required()])
#     
#     # role = 
#     
#     
@app.route("/volunteers/shifts", methods=['GET', 'POST'])
def volunteers_shifts():
    
    slots = {31:{}, 1:{}, 2:{}}
    # slots = []
    for ss in ShiftSlot.query.order_by(ShiftSlot.start_time).all():
        
        if not ss.role.name in slots[ss.start_time.day]:
            slots[ss.start_time.day][ss.role.name] = [ss.start_time.hour,]
        else:
            slots[ss.start_time.day][ss.role.name].append(ss.start_time.hour)
        
        # slots[ss.start_time.day].append((ss.start_time.hour, ss.role.name))
        # slots.append(ss)
    return render_template('volunteer_shifts.html', slots=slots)