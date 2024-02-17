from flask_wtf import FlaskForm
from wtforms import SelectField, StringField


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


class DiversityForm(Form):
    age = StringField("Age")
    gender = StringField("Gender")
    ethnicity = StringField("Ethnicity")

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
            self.age.data = user.diversity.age
            self.gender.data = user.diversity.gender
            self.ethnicity.data = user.diversity.ethnicity

        if user.cfp_reviewer_tags:
            self.cfp_tag_0.data = user.cfp_reviewer_tags[0].tag
            self.cfp_tag_1.data = user.cfp_reviewer_tags[1].tag
            self.cfp_tag_2.data = user.cfp_reviewer_tags[2].tag

        return self
