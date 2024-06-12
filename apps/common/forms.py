import re
from typing import Pattern

from flask import current_app as app
from flask_wtf import FlaskForm

from wtforms import SelectField, BooleanField, ValidationError
from wtforms.validators import InputRequired

from models.user import UserDiversity
from models.cfp_tag import DEFAULT_TAGS, Tag
from models.purchase import AdmissionTicket

from .fields import HiddenIntegerField, MultiCheckboxField


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

NULL_SELECTION = [
    ("", "(please choose)"),
]

GENDER_VALUES = ("female", "male", "non-binary", "other")
GENDER_CHOICES = tuple(OPT_OUT + [(v, v.capitalize()) for v in GENDER_VALUES])

ETHNICITY_VALUES = ("asian", "black", "mixed", "white", "other")
ETHNICITY_CHOICES = tuple(OPT_OUT + [(v, v.capitalize()) for v in ETHNICITY_VALUES])

AGE_VALUES = ("0-15", "16-25", "26-35", "36-45", "46-55", "56-65", "66+")
AGE_CHOICES = tuple(OPT_OUT + [(v, v) for v in AGE_VALUES])

SEXUALITY_VALUES = (
    "straight-or-heterosexual",
    "gay-or-lesbian",
    "bisexual-or-pansexual",
    "other",
)
SEXUALITY_CHOICES = tuple(
    OPT_OUT + [(v, v.capitalize().replace("-", " ")) for v in SEXUALITY_VALUES]
)


DISABILITY_CHOICES = tuple(
    [
        ("physical", "Physical disability or mobility issue"),
        ("vision", "Blindness or a visual impairment not corrected by glasses"),
        ("hearing", "Deafness or a serious hearing impairment"),
        ("autism-adhd", "Autistic spectrum condition, Asperger's, or ADHD"),
        ("long-term", "Long-term illness"),
        ("mental-health", "Mental health condition"),
        ("other", "Another condition not mentioned here"),
        ("none", "None of the above"),
    ]
)


TOPIC_CHOICES = tuple(NULL_SELECTION + [(v, v.capitalize()) for v in DEFAULT_TAGS])

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
    sexuality = SelectField("Sexuality", default=OPT_OUT[0], choices=SEXUALITY_CHOICES)
    disability = MultiCheckboxField("Disability", choices=DISABILITY_CHOICES)

    # Track CfP reviewer tags
    cfp_tag_0 = SelectField("Topic 1", choices=TOPIC_CHOICES)
    cfp_tag_1 = SelectField("Topic 2", choices=TOPIC_CHOICES)
    cfp_tag_2 = SelectField("Topic 3", choices=TOPIC_CHOICES)

    cfp_tags_required: bool

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cfp_tags_required = user.has_permission("cfp_reviewer")
        if not self.cfp_tags_required:
            del self.cfp_tag_0
            del self.cfp_tag_1
            del self.cfp_tag_2

    def update_user(self, user):
        if not user.diversity:
            user.diversity = UserDiversity()

        user.diversity.age = self.age.data
        user.diversity.gender = self.gender.data
        user.diversity.ethnicity = self.ethnicity.data
        user.diversity.sexuality = self.sexuality.data
        user.diversity.disability = self.disability.data

        if self.cfp_tags_required:
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
            self.sexuality.data = user.diversity.sexuality
            self.disability.data = user.diversity.disability

        if self.cfp_tags_required and user.cfp_reviewer_tags:
            self.cfp_tag_0.data = user.cfp_reviewer_tags[0].tag
            self.cfp_tag_1.data = user.cfp_reviewer_tags[1].tag
            self.cfp_tag_2.data = user.cfp_reviewer_tags[2].tag

        return self

    def validate_disability(form, field):
        if len(field.data) > 1 and "none" in field.data:
            raise ValidationError("Cannot select 'no disability' and a disability")
        elif len(field.data) > 1 and "" in field.data:
            raise ValidationError("Cannot select 'prefer not to say' and a disability")

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        result = True
        if self.cfp_tags_required:
            seen = set()
            for field in [self.cfp_tag_0, self.cfp_tag_1, self.cfp_tag_2]:
                if field.data == "":
                    field.errors = ["Please select a topic."]
                    result = False
                elif field.data in seen:
                    field.errors = ["Please select three different choices."]
                    result = False
                else:
                    seen.add(field.data)
        return result


class RefundPurchaseForm(Form):
    purchase_id = HiddenIntegerField("Purchase ID", [InputRequired()])
    refund = BooleanField("Refund purchase", default=True)


def update_refund_purchase_form_details(f, purchase, ignore_event_refund_state=False):
    f._purchase = purchase
    f.refund.label.text = "%s - %s" % (
        f._purchase.id,
        f._purchase.product.display_name,
    )

    f.refund.data = False

    if purchase.is_refundable(ignore_event_refund_state):
        f._disabled = False

    else:
        f._disabled = True

        if purchase.redeemed:
            if type(purchase) is AdmissionTicket:
                f.refund.label.text += " (checked in)"
            else:
                f.refund.label.text += " (redeemed)"

        elif purchase.state == "refunded":
            f.refund.label.text += " (refunded)"

        elif purchase.state == "refund-pending":
            f.refund.label.text += " (refunded requested)"

        elif purchase.is_transferred:
            f.refund.label.text += " (transferred)"
