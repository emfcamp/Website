import re

from collections import defaultdict
from typing import Pattern

from flask import current_app as app

from main import db
from . import BaseModel


OPT_OUT = [
    ("", "Prefer not to say"),
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


class UserDiversity(BaseModel):
    __tablename__ = "diversity"
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, primary_key=True
    )
    age = db.Column(db.String)
    gender = db.Column(db.String)
    ethnicity = db.Column(db.String)
    disability = db.Column(db.String)
    sexuality = db.Column(db.String)

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
                "ages": guess_age(row.age),
                "genders": guess_gender(row.gender),
                "ethnicities": guess_ethnicity(row.ethnicity),
                "sexualities": row.sexuality or "",
                "disabilities": row.disability or "",
            }

            update_diversity_dict(data["totals"], parsed_values)

            user = row.user
            if user.has_proposals:
                update_diversity_dict(data["submitted_a_proposal"], parsed_values)

            if user.is_cfp_accepted:
                update_diversity_dict(data["speakers"], parsed_values)

            if user.is_cfp_accepted and user.is_invited_speaker:
                update_diversity_dict(data["invited_speakers"], parsed_values)

            if user.is_cfp_accepted and not user.is_invited_speaker:
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
