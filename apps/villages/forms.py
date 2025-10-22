from geoalchemy2.shape import from_shape, to_shape
from shapely import Point
from wtforms import (
    FloatField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import URL, Length, Optional

from models import Village
from models.village import VillageRequirements

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

    def populate(self, village: Village) -> None:
        self.name.data = village.name
        self.description.data = village.description
        self.url.data = village.url

        requirements = village.requirements
        if requirements is not None:
            self.num_attendees.data = requirements.num_attendees
            self.size_sqm.data = requirements.size_sqm
            self.power_requirements.data = requirements.power_requirements
            self.noise.data = requirements.noise
            self.structures.data = requirements.structures

    def populate_obj(self, village: Village) -> None:
        assert self.name.data is not None
        village.name = self.name.data
        village.description = self.description.data
        village.url = self.url.data

        if village.requirements is None:
            village.requirements = VillageRequirements()

        village.requirements.num_attendees = self.num_attendees.data
        village.requirements.size_sqm = self.size_sqm.data
        village.requirements.power_requirements = self.power_requirements.data
        village.requirements.noise = self.noise.data
        village.requirements.structures = self.structures.data

    def validate_name(self, field: StringField) -> None:
        field.data = (field.data or "").strip()


class AdminVillageForm(VillageForm):
    lat = FloatField("Latitude", [Optional()])
    lon = FloatField("Longitude", [Optional()])

    def populate(self, village: Village) -> None:
        super().populate(village)

        if village.location is None:
            self.lat.data = None
            self.lon.data = None
        else:
            latlon = to_shape(village.location)
            self.lat.data = latlon.y
            self.lon.data = latlon.x

    def populate_obj(self, village: Village) -> None:
        super().populate_obj(village)

        if self.lat.data is not None and self.lon.data is not None:
            village.location = from_shape(Point(self.lon.data, self.lat.data))
        else:
            village.location = None
