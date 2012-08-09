from main import app
from flask import render_template, request, redirect, url_for
from flaskext.login import current_user
from flaskext.wtf import Form, TextField, Email, Required, IntegerField
from users import NextURLField

class VolunteerLogin(Form):
    email = TextField('Email', [Email(), Required()])
    phone_number = IntegerField('Number', [Required()])
    next = NextURLField('Next')
    
@app.route("/volunteer_login", methods=['GET', 'POST'])
def volunteer_login():
    if not current_user.is_authenticated():
        return redirect(request.args.get('next', url_for('login')))
    form = VolunteerLogin(request.form, next=request.args.get('next'))
    # if request.method == 'POST' and form.validate():
        # user = User.query.filter_by(email=form.email.data).first()
        # if user and user.check_password(form.password.data):
        #     login_user(user)
        #     return redirect(form.next.data or url_for('tickets'))
        # else:
        #     flash("Invalid login details!")
    return render_template('volunteer-login.html', form=form)


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

