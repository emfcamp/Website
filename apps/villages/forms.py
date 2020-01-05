from wtforms import SubmitField, StringField, SelectField, TextAreaField, IntegerField
from wtforms.validators import Optional, Length

from ..common.forms import Form


class VillageForm(Form):
    name = StringField("Village Name", [Length(2, 25)])
    description = TextAreaField("Description", [Optional()])

    num_attendees = IntegerField("Number of People", [Optional()])
    size_sqm = IntegerField("Size (square metres)", [Optional()])

    power_requirements = TextAreaField("Power Requirements", [Optional()])

    noise = SelectField(
        "Noise Level",
        [Optional()],
        choices=[
            ("", ""),
            ("family", "Family"),
            ("quiet", "Quiet"),
            ("medium", "Socialising/quiet music"),
            ("loud", "Loud music"),
        ],
        default="",
    )

    structures = TextAreaField("Large structures", [Optional()])

    submit = SubmitField("Submit")

    def populate(self, village):
        self.name.data = village.name
        self.description.data = village.description

        requirements = village.requirements

        self.num_attendees.data = requirements.num_attendees
        self.size_sqm.data = requirements.size_sqm
        self.power_requirements.data = requirements.power_requirements
        self.noise.data = requirements.noise
        self.structures.data = requirements.structures
