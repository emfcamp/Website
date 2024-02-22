from flask_wtf import FlaskForm
from wtforms import SelectField, StringField


from models.user_diverstiy import (
    AGE_OPTIONS,
    ETHNICITY_OPTIONS,
    GENDER_OPTIONS,
    UserDiversity,
)
from models.cfp_tag import DEFAULT_TAGS, Tag


class Form(FlaskForm):
    """
    Re-override these back to their wtforms defaults
    """

    class Meta(FlaskForm.Meta):
        csrf = False
        csrf_class = None
        csrf_context = None


def __generate_choices(choices):
    return [
        ("", "Prefer not to say"),
    ] + [(i, i) for i in choices]


AGE_CHOICES = __generate_choices(AGE_OPTIONS)
GENDER_CHOICES = __generate_choices(GENDER_OPTIONS)
ETHNICITY_CHOICES = __generate_choices(ETHNICITY_OPTIONS)


class DiversityForm(Form):
    age = SelectField("Age", choices=AGE_CHOICES)
    gender = SelectField("Gender", choices=GENDER_CHOICES)
    gender_other = StringField("Other gender not listed (select 'Other')")
    ethnicity = SelectField("Ethnicity", choices=ETHNICITY_CHOICES)

    # Track CfP reviewer tags
    cfp_tag_0 = SelectField("Topic 1", default=DEFAULT_TAGS[0], choices=DEFAULT_TAGS)
    cfp_tag_1 = SelectField("Topic 2", default=DEFAULT_TAGS[1], choices=DEFAULT_TAGS)
    cfp_tag_2 = SelectField("Topic 3", default=DEFAULT_TAGS[2], choices=DEFAULT_TAGS)

    def update_user(self, user):
        if not user.diversity:
            user.diversity = UserDiversity()

        user.diversity.age = self.age.data
        user.diversity.gender = (
            self.gender_other.data if self.gender.data == "Other" else self.gender.data
        )
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
            self.age.data = user.diversity.age
            self.ethnicity.data = user.diversity.ethnicity

            gender = user.diversity.gender
            # If gender is empty string then it's "Prefer not to say"
            if gender and gender not in GENDER_OPTIONS:
                self.gender.data = "Other"
                self.gender_other.data = gender
            else:
                self.gender.data = gender
                # leave gender_other unset

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
