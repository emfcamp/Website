from collections import defaultdict

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.user import User

from . import BaseModel

__all__ = ["UserDiversity"]

OPT_OUT = [
    ("", "Prefer not to say"),
]

GENDER_VALUES = ("female", "male", "non-binary", "other")
GENDER_CHOICES = tuple(OPT_OUT + [(v, v.capitalize()) for v in GENDER_VALUES])

# These choices are derived from the top-level categories in the Ethnicity Harmonised Standard
# so the numbers can easily be compared to the UK census.
# https://analysisfunction.civilservice.gov.uk/policy-store/ethnicity-harmonised-standard/
#
# We don't collect the more granular categories here, to minimise data collected.
ETHNICITY_CHOICES = [
    ("", "Prefer not to say"),
    ("white", "White"),
    ("mixed", "Mixed/multiple ethnic groups"),
    ("asian", "Asian"),
    ("black", "Black/African/Caribbean"),
    ("arab", "Arab"),
    ("other", "Other ethnic group"),
]

AGE_VALUES = ("0-15", "16-25", "26-35", "36-45", "46-55", "56-65", "66+")
AGE_CHOICES = tuple(OPT_OUT + [(v, v) for v in AGE_VALUES])

SEXUALITY_VALUES = (
    "straight-or-heterosexual",
    "gay-or-lesbian",
    "bisexual-or-pansexual",
    "other",
)
SEXUALITY_CHOICES = tuple(OPT_OUT + [(v, v.capitalize().replace("-", " ")) for v in SEXUALITY_VALUES])


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


class UserDiversity(BaseModel):
    __tablename__ = "diversity"
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    age: Mapped[str | None]
    gender: Mapped[str | None]
    ethnicity: Mapped[str | None]
    disability: Mapped[str | None]
    sexuality: Mapped[str | None]

    user: Mapped[User] = relationship(back_populates="diversity")

    @classmethod
    def get_export_data(cls):
        data = {
            "totals": {
                "ages": defaultdict(int),
                "genders": defaultdict(int),
                "ethnicities": defaultdict(int),
                "disabilities": defaultdict(int),
                "sexualities": defaultdict(int),
            },
            "submitted_a_proposal": {
                "ages": defaultdict(int),
                "genders": defaultdict(int),
                "ethnicities": defaultdict(int),
                "disabilities": defaultdict(int),
                "sexualities": defaultdict(int),
            },
            "speakers": {
                "ages": defaultdict(int),
                "genders": defaultdict(int),
                "ethnicities": defaultdict(int),
                "disabilities": defaultdict(int),
                "sexualities": defaultdict(int),
            },
            "invited_speakers": {
                "ages": defaultdict(int),
                "genders": defaultdict(int),
                "ethnicities": defaultdict(int),
                "disabilities": defaultdict(int),
                "sexualities": defaultdict(int),
            },
            "non-invited_speakers": {
                "ages": defaultdict(int),
                "genders": defaultdict(int),
                "ethnicities": defaultdict(int),
                "disabilities": defaultdict(int),
                "sexualities": defaultdict(int),
            },
            "cfp_reviewers": {
                "ages": defaultdict(int),
                "genders": defaultdict(int),
                "ethnicities": defaultdict(int),
                "disabilities": defaultdict(int),
                "sexualities": defaultdict(int),
            },
        }

        for row in cls.query:
            parsed_values = {
                "ages": row.age,
                "genders": row.gender,
                "ethnicities": row.ethnicity,
                "sexualities": row.sexuality or "",
                "disabilities": row.disability or "",
            }

            update_diversity_dict(data["totals"], parsed_values)

            user = row.user
            if user.proposals:
                update_diversity_dict(data["submitted_a_proposal"], parsed_values)

            # FIXME: this isn't just speakers
            if user.has_accepted_proposal:
                update_diversity_dict(data["speakers"], parsed_values)

            if user.has_accepted_proposal and user.is_invited_speaker:
                update_diversity_dict(data["invited_speakers"], parsed_values)

            if user.has_accepted_proposal and not user.is_invited_speaker:
                update_diversity_dict(data["non-invited_speakers"], parsed_values)

            if user.has_permission("cfp_reviewer", cascade=False):
                update_diversity_dict(data["cfp_reviewers"], parsed_values)

        return {
            "private": {"diversity": data},
            "tables": ["diversity"],
        }


def update_diversity_dict(to_update, vals):
    for k, v in vals.items():
        if k is None:
            k = ""
        to_update[k][v] += 1
