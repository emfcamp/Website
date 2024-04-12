import re
from typing import Pattern

from flask import current_app as app
from flask_wtf import FlaskForm
from wtforms import SelectField, BooleanField, FieldList, FormField, SubmitField
from wtforms.validators import InputRequired

from .fields import HiddenIntegerField

from models.user import UserDiversity
from models.cfp_tag import DEFAULT_TAGS, Tag


class Form(FlaskForm):
    """
    Re-override these back to their wtforms defaults
    """

    class Meta(FlaskForm.Meta):
        csrf = False
        csrf_class = None
        csrf_context = None


OPT_OUT = [
    ("", "Prefer not to say"),
]

GENDER_VALUES = ("female", "male", "non-binary", "other")
GENDER_CHOICES = tuple(OPT_OUT + [(v, v.capitalize()) for v in GENDER_VALUES])

ETHNICITY_VALUES = ("asian", "black", "mixed", "white", "other")
ETHNICITY_CHOICES = tuple(OPT_OUT + [(v, v.capitalize()) for v in ETHNICITY_VALUES])

AGE_VALUES = ("0-15", "16-25", "26-35", "36-45", "46-55", "56-65", "66+")
AGE_CHOICES = tuple(OPT_OUT + [(v, v) for v in AGE_VALUES])


# FIXME these are matchers for transition from freetext diversity form -> select boxes
# This should be deleted for 2026


def guess_age(age_str: str) -> str:
    if age_str in AGE_VALUES:
        return age_str
    try:
        age = int(age_str)
    except ValueError:  # Can't parse as an int so reset
        return ""

    if age > 66:
        return "66+"

    for age_range in AGE_VALUES:
        if age_range == "66+":
            continue
        low_val, high_val = age_range.split("-")

        if int(low_val) <= age <= int(high_val):
            return age_range

    return ""


def __guess_value(match_str: str, matchers_dict: dict[str, Pattern]) -> str:
    match_str = match_str.lower().strip()
    for key, matcher in matchers_dict.items():
        if matcher.fullmatch(match_str):
            return key

    return ""


def guess_gender(gender_str: str) -> str:
    gender_matchers = app.config.get("GENDER_MATCHERS", {})
    gender_re_matchers = {k: re.compile(v, re.I) for k, v in gender_matchers.items()}
    return __guess_value(gender_str, gender_re_matchers)


def guess_ethnicity(ethnicity_str: str) -> str:
    ethnicity_matchers = app.config.get("ETHNICITY_MATCHERS", {})
    ethnicity_re_matchers = {
        k: re.compile(v, re.I) for k, v in ethnicity_matchers.items()
    }
    return __guess_value(ethnicity_str, ethnicity_re_matchers)


# End of stuff to delete for 2026


class DiversityForm(Form):
    age = SelectField("Age", default=OPT_OUT[0], choices=AGE_CHOICES)
    gender = SelectField("Gender", default=OPT_OUT[0], choices=GENDER_CHOICES)
    ethnicity = SelectField("Ethnicity", default=OPT_OUT[0], choices=ETHNICITY_CHOICES)

    # Track CfP reviewer tags
    cfp_tag_0 = SelectField("Topic 1", default=DEFAULT_TAGS[0], choices=DEFAULT_TAGS)
    cfp_tag_1 = SelectField("Topic 2", default=DEFAULT_TAGS[1], choices=DEFAULT_TAGS)
    cfp_tag_2 = SelectField("Topic 3", default=DEFAULT_TAGS[2], choices=DEFAULT_TAGS)

    def update_user(self, user):
        if not user.diversity:
            user.diversity = UserDiversity()

        user.diversity.age = self.age.data
        user.diversity.gender = self.gender.data
        user.diversity.ethnicity = self.ethnicity.data

        if user.has_permission("cfp_reviewer"):
            user.cfp_reviewer_tags = [
                Tag.get_by_value(self.cfp_tag_0.data),
                Tag.get_by_value(self.cfp_tag_1.data),
                Tag.get_by_value(self.cfp_tag_2.data),
            ]

        return user

    def set_from_user(self, user):
        if user.diversity:
            self.age.data = guess_age(user.diversity.age)
            self.gender.data = guess_gender(user.diversity.gender)
            self.ethnicity.data = guess_ethnicity(user.diversity.ethnicity)

        if user.cfp_reviewer_tags:
            self.cfp_tag_0.data = user.cfp_reviewer_tags[0].tag
            self.cfp_tag_1.data = user.cfp_reviewer_tags[1].tag
            self.cfp_tag_2.data = user.cfp_reviewer_tags[2].tag

        return self

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        result = True
        seen = set()
        for field in [self.cfp_tag_0, self.cfp_tag_1, self.cfp_tag_2]:
            if field.data in seen:
                field.errors = ["Please select three different choices."]
                result = False
            else:
                seen.add(field.data)
        return result


class RefundPurchaseForm(Form):
    purchase_id = HiddenIntegerField("Purchase ID", [InputRequired()])
    refund = BooleanField("Refund purchase", default=True)


class RefundForm(Form):
    purchases = FieldList(FormField(RefundPurchaseForm))
    refund = SubmitField("Refunded these by bank transfer")
    stripe_refund = SubmitField("Refund through Stripe (preferred)")
