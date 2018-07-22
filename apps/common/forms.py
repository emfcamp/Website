# encoding=utf-8
from flask import Markup

from flask_wtf import Form as BaseForm
from flask_wtf.form import _is_hidden

from wtforms import (
    IntegerField, SelectField,
)
from wtforms.widgets import Input, HiddenInput
from wtforms.fields import StringField
from wtforms.compat import string_types
from wtforms.widgets.core import html_params


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


class HiddenIntegerField(IntegerField):
    widget = HiddenInput()


class TelInput(Input):
    input_type = 'tel'


class TelField(StringField):
    widget = TelInput()


class StaticWidget(object):
    """
    Render a Bootstrap ``form-control-static`` div.

    Used for when fields aren't editable. Call render_static in template.
    """
    def __call__(self, field, **kwargs):
        kwargs.setdefault('id', field.id)
        if 'class_' in kwargs:
            kwargs['class_'] = 'form-control-static %s' % kwargs['class_']
        else:
            kwargs['class_'] = 'form-control-static'

        return Markup('<div %s>%s</div>' % (html_params(**kwargs), field._value()))

class StaticField(StringField):
    widget = StaticWidget()


class Form(BaseForm):
    # CsrfProtect token limit, to match the flask permanent session expiry of 31 days.
    TIME_LIMIT = 3600 * 24 * 31

    def hidden_tag_without(self, *exclude_fields):
        fields = [isinstance(f, string_types) and getattr(self, f) or f for f in exclude_fields]
        keep_fields = [f for f in self if _is_hidden(f) and f not in fields]
        return BaseForm.hidden_tag(self, *keep_fields)

