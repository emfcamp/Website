from wtforms import StringField, TextAreaField, SubmitField
from wtforms.validators import ValidationError

from ..common.forms import Form


class SendMessageForm(Form):
    subject = StringField("Subject")
    message = TextAreaField("Message")
    send = SubmitField("Send Message")

    def validate_message(form, field):
        if form.send.data and not field.data:
            raise ValidationError("Message is required")

    def validate_subject(form, field):
        if form.send.data and not field.data:
            raise ValidationError("Subject is required")
