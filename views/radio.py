from main import db, app

from flask import render_template, request, redirect, url_for, flash
from flaskext.wtf import Form, Required, \
    SelectField, IntegerField, HiddenField, BooleanField, SubmitField, \
    FieldList, FormField, StringField, ValidationError

@app.route("/radio", methods=['GET'])
def radio():
    return render_template('radio.html')

