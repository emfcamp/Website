from flask import (
    render_template, current_app as app
)
from flask_login import current_user

from wtforms import (
    StringField, IntegerField
)
from wtforms.validators import Required, Email

from ..common.forms import Form
from . import volunteering


class VolunteerSignUpForm(Form):
    name = StringField("Name", [Required()])
    email = StringField("Email", [Email(), Required()])
    age = IntegerField("Age", [Required()])
    phone_number = StringField("Phone Number", [Required()])


@volunteering.route('/sign-up')
def sign_up():
    form = VolunteerSignUpForm()
    # On sign up give user 'volunteer' permission (+ managers etc.)
    return render_template('volunteering/sign-up.html',
                           user=current_user,
                           form=form)
