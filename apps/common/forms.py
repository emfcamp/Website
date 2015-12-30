# encoding=utf-8
from flask_wtf import Form as BaseForm
from flask_wtf.form import _is_hidden

from wtforms import (
    IntegerField, SelectField, HiddenField,
)
from wtforms.widgets import Input
from wtforms.fields import StringField
from wtforms.compat import string_types


class IntegerSelectField(SelectField):
    def __init__(self, *args, **kwargs):
        kwargs['coerce'] = int
        self.fmt = kwargs.pop('fmt', str)
        self.values = kwargs.pop('values', [])
        SelectField.__init__(self, *args, **kwargs)

    @property
    def values(self):
        return self._values

    @values.setter
    def values(self, vals):
        self._values = vals
        self.choices = [(i, self.fmt(i)) for i in vals]


class HiddenIntegerField(HiddenField, IntegerField):
    """
    widget=HiddenInput() doesn't work with WTF-Flask's hidden_tag()
    """


class HiddenStringField(HiddenField, StringField):
    """
    Replication of HiddenIntegerField for strings.
    """


class TelInput(Input):
    input_type = 'tel'


class TelField(StringField):
    widget = TelInput()


class Form(BaseForm):
    # CsrfProtect limit
    TIME_LIMIT = 3600 * 24

    def hidden_tag_without(self, *fields):
        fields = [isinstance(f, string_types) and getattr(self, f) or f for f in fields]
        keep_fields = [f for f in self if _is_hidden(f) and f not in fields]
        return BaseForm.hidden_tag(self, *keep_fields)
