from wtforms import (
    SubmitField,
    StringField,
    SelectField,
    TextAreaField,
    IntegerField,
)
from wtforms.validators import Optional, Length, URL
from geoalchemy2.shape import to_shape

from ..common.forms import Form


class VillageForm(Form):
    name = StringField("Village Name", [Length(2, 25)])
    description = TextAreaField("Description", [Optional()])
    url = StringField("URL", [URL(), Optional()])

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
        self.url.data = village.url

        requirements = village.requirements

        self.num_attendees.data = requirements.num_attendees
        self.size_sqm.data = requirements.size_sqm
        self.power_requirements.data = requirements.power_requirements
        self.noise.data = requirements.noise
        self.structures.data = requirements.structures

    def validate_name(form, field):
        field.data = field.data.strip()

class AdminVillageForm(VillageForm):
    latlon = StringField("Location", [Optional()])

    def populate(self, village):
        super().populate(village)

        if village.location is None:
            self.latlon.data = ""
        else:
            latlon = to_shape(village.location)
            self.latlon.data = "{}, {}".format(latlon.x, latlon.y)

    def populate_obj(self, village):
        village.name = self.name.data
        village.description = self.description.data
        village.url = self.url.data
        if self.latlon.data:
            latlon = self.latlon.data.split(",")
            location = f"POINT({latlon[0]} {latlon[1]})"
        else:
            location = None
        village.location = location

        village.requirements.num_attendees = self.num_attendees.data
        village.requirements.size_sqm = self.size_sqm.data
        village.requirements.power_requirements = self.power_requirements.data
        village.requirements.noise = self.noise.data
        village.requirements.structures = self.structures.data
