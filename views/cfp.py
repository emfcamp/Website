from main import app, db
from views import TelField, Form, feature_flag
from models.cfp import Proposal

from flask import (
    render_template, redirect, request, flash,
    url_for, session,
)
from flask.ext.login import current_user

from sqlalchemy.orm.exc import NoResultFound

from wtforms.validators import Required, Email
from wtforms import (
    SubmitField, BooleanField, TextField,
    DecimalField, FieldList, FormField,
    TextAreaField,
)

from datetime import datetime, timedelta

class ProposalForm(Form):
    email = TextField('Email', [Email(), Required()])
    name = TextField('Name', [Required()])
    title = TextField('Title', [Required()])
    description = TextAreaField('Description', [Required()])
    length = TextField('Duration', [Required()])
    propose = TextField('Submit')

@feature_flag('CFP')
@app.route('/cfp', methods=['GET', 'POST'])
def cfp():
    form = ProposalForm()
    if form.validate_on_submit():
        prop = Proposal()
        prop.title = form.title.data
        prop.email = form.email.data
        prop.description = form.description.data
        prop.length = form.length.data

        db.session.add(prop)
        db.session.commit()

        return redirect(url_for('cfp_complete'))

    if current_user.is_authenticated():
        form.email.data = current_user.email

    return render_template('cfp.html', form=form)

@feature_flag('CFP')
@app.route('/cfp/complete')
def cfp_complete():
    return render_template('cfp_complete.html')

