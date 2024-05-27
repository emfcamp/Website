import json

from markupsafe import Markup
from wtforms import IntegerField, SelectField, StringField, ValidationError
from wtforms.widgets import Input, HiddenInput
from wtforms.widgets.html5 import EmailInput
from wtforms.widgets.core import html_params
from email_validator import validate_email, EmailNotValidError
import re


class EmailField(StringField):
    """HTML5 email field using the email_validator package to perform
    enhanced email validation.

    You don't need to provide additional validators to this field.
    """

    widget = EmailInput()

    def pre_validate(self, form):
        try:
            result = validate_email(self.data)
            # Replace data with normalised version of email
            self.data = result["email"]
        except EmailNotValidError as e:
            raise ValidationError(str(e))


class IntegerSelectField(SelectField):
    def __init__(self, *args, **kwargs):
        kwargs["coerce"] = int
        self.fmt = kwargs.pop("fmt", str)
        self.values = kwargs.pop("values", [])
        SelectField.__init__(self, *args, **kwargs)

    @property
    def values(self):
        return self._values

    @values.setter
    def values(self, vals):
        self._values = vals
        self.choices = [(i, self.fmt(i)) for i in vals]


class HiddenIntegerField(IntegerField):
    widget = HiddenInput()


class TelInput(Input):
    input_type = "tel"


class TelField(StringField):
    widget = TelInput()

    def __init__(self, *args, **kwargs):
        self.min_length = kwargs.pop("min_length", 8)
        self.max_length = kwargs.pop("max_length", 20)
        StringField.__init__(self, *args, **kwargs)

    def pre_validate(form, field):
        if re.search(r"^\s*$", form.data):
            # Allow empty field or only whitespace in field, this can be handled by Required()
            return

        if not re.search(r"^\+?[0-9 \-]+$", form.data):
            raise ValidationError(
                "A telephone number may only contain numbers, spaces or dashes."
            )

        if not form.min_length <= len(form.data) <= form.max_length:
            raise ValidationError(
                f"Must be between {form.min_length} and {form.max_length} digits."
            )


class JSONField(StringField):
    def _value(self):
        return json.dumps(self.data) if self.data else ""

    def process_formdata(self, valuelist):
        if valuelist and valuelist[0] != "":
            try:
                self.data = json.loads(valuelist[0])
            except ValueError:
                raise ValueError("This field contains invalid JSON")
        else:
            self.data = {}

    def pre_validate(self, form):
        super().pre_validate(form)
        if self.data:
            try:
                json.dumps(self.data)
            except TypeError:
                raise ValueError("This field contains invalid JSON")


class StaticWidget(object):
    """
    Render a Bootstrap ``form-control-static`` div.

    Used for when fields aren't editable. Call render_static in template.
    """

    def __call__(self, field, **kwargs):
        kwargs.setdefault("id", field.id)
        if "class_" in kwargs:
            kwargs["class_"] = "form-control-static %s" % kwargs["class_"]
        else:
            kwargs["class_"] = "form-control-static"

        return Markup("<div %s>%s</div>" % (html_params(**kwargs), field._value()))


class StaticField(StringField):
    widget = StaticWidget()
