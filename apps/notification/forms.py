import dateutil
from wtforms import (
    SubmitField, StringField, FieldList, FormField, SelectField, TextAreaField,
    BooleanField, IntegerField, FloatField
)
from wtforms.validators import Required, NumberRange, ValidationError

from ..common.forms import Form, HiddenIntegerField


class SendMessageForm(Form):
    subject = StringField('Subject')
    message = TextAreaField('Message')
    send = SubmitField('Send Message')
    
    def validate_message(form, field):
        if form.send.data and not field.data:
            raise ValidationError("Message is required")

    def validate_subject(form, field):
        if form.send.data and not field.data:
            raise ValidationError("Subject is required")