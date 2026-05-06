from wtforms import HiddenField, StringField, SubmitField, TextAreaField
from wtforms.validators import InputRequired, Length, Optional, Regexp, ValidationError

from models.wiki import WikiPage

from ..common.forms import Form


class WikiPageForm(Form):
    title = StringField("Title", [InputRequired(), Length(1, 200)])
    content = TextAreaField("Content", [Optional()])
    version_token = HiddenField()
    submit = SubmitField("Save")


class CreateWikiPageForm(WikiPageForm):
    slug = StringField(
        "URL slug",
        [
            InputRequired(),
            Length(1, 100),
            Regexp(
                r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
                message="Slug must be lowercase letters, digits and hyphens only (e.g. ride-share)",
            ),
        ],
    )
    submit = SubmitField("Create page")

    def validate_slug(self, field: StringField) -> None:
        if field.data is not None and WikiPage.get_by_slug(field.data):
            raise ValidationError("A wiki page with this slug already exists.")
