from flask_wtf import FlaskForm
from wtforms import BooleanField, SelectField, ValidationError
from wtforms.validators import InputRequired

from models.cfp_tag import DEFAULT_TAGS, Tag
from models.diversity import (
    AGE_CHOICES,
    DISABILITY_CHOICES,
    ETHNICITY_CHOICES,
    GENDER_CHOICES,
    OPT_OUT,
    SEXUALITY_CHOICES,
    UserDiversity,
    guess_age,
    guess_ethnicity,
    guess_gender,
)
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


NULL_SELECTION = [
    ("", "(please choose)"),
]
TOPIC_CHOICES = tuple(NULL_SELECTION + [(v, v.capitalize()) for v in DEFAULT_TAGS])


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
        if len(field.data) > 1 and "" in field.data:
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
    f.refund.label.text = f"{f._purchase.id} - {f._purchase.product.display_name}"

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
