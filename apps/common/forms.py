import re
from typing import Pattern

from flask_wtf import FlaskForm
from wtforms import SelectField

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


# FIXME Helper stuff for transition from freetext diversity form -> select boxes
# This should be deleted for 2026
OPT_OUT = [
    ("", "Prefer not to say"),
]
GENDER_MATCHERS = {
    "female": re.compile(r"^(female|woman|f|fem|femme)$", re.I),
    "male": re.compile(r"^(male|man|m|masc)$", re.I),
    "non-binary": re.compile(r"^(nb|enby|non[ -]?binary)$", re.I),
    "transman": re.compile(r"^trans[ -]?(man|masc)$", re.I),
    "transwoman": re.compile(r"^trans[ -]?(woman|fem|femme)$", re.I),
    "other": re.compile(r"^other$", re.I),
}
GENDER_CHOICES = tuple([(v, v.capitalize()) for v in GENDER_MATCHERS.keys()] + OPT_OUT)


ETHNICITY_MATCHERS = {
    "asian": re.compile(r"^(asian|indian|chinese|pakistani)$", re.I),
    "black": re.compile(r"^(black ?(british)?)$", re.I),
    "mixed": re.compile(r"^mixed$", re.I),
    "white": re.compile(
        (
            # white, white british, white uk etc.
            r"^(white ?(british|irish|welsh|scottish|uk|european|english)?"
            # just british, caucasian etc.
            r"|caucasian|british|irish|welsh|scottish|uk|european|english)$"
        ),
        re.I,
    ),
    "other": re.compile(r"^other$", re.I),
}
ETHNICITY_CHOICES = tuple(
    [(v, v.capitalize()) for v in ETHNICITY_MATCHERS.keys()] + OPT_OUT
)

AGE_VALUES = ("0-15", "16-25", "26-35", "36-45", "46-55", "56-65", "66+")
AGE_CHOICES = tuple([(v, v) for v in AGE_VALUES] + OPT_OUT)


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
    return __guess_value(gender_str, GENDER_MATCHERS)


def guess_ethnicity(ethnicity_str: str) -> str:
    return __guess_value(ethnicity_str, ETHNICITY_MATCHERS)


# End of stuff to delete for 2026


class DiversityForm(Form):
    age = SelectField("Age", choices=AGE_CHOICES)
    gender = SelectField("Gender", choices=GENDER_CHOICES)
    ethnicity = SelectField("Ethnicity", choices=ETHNICITY_CHOICES)

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
