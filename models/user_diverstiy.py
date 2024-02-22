import re
from collections import defaultdict

from main import db

from . import bucketise, BaseModel


AGE_OPTIONS = (
    "Under 16",
    "17 or 18",
    "19 to 25",
    "25 to 35",
    "35 to 50",
    "50 to 65",
    "Over 66",
)


GENDER_OPTIONS = (
    "Male",
    "Female",
    "Non-Binary",
    "Other",
)


ETHNICITY_OPTIONS = (
    "White",
    "Asian",
    "Black",
    "Mixed",
    "Other",
)


class UserDiversity(BaseModel):
    __tablename__ = "diversity"
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, primary_key=True
    )
    age = db.Column(db.String)
    gender = db.Column(db.String)
    ethnicity = db.Column(db.String)

    @classmethod
    def get_export_data(cls):
        valid_ages = []
        ages = defaultdict(int)
        sexes = defaultdict(int)
        ethnicities = defaultdict(int)

        for row in cls.query:
            matches = re.findall(r"\b[0-9]{1,3}\b", row.age)
            if matches:
                valid_ages += map(int, matches)
            elif not row.age:
                ages[""] += 1
            else:
                ages["other"] += 1

            # Someone might put "more X than Y" or "both X",
            # but this mostly works. 'other' includes the error rate.
            matches_m = re.findall(r"\b(male|man|m)\b", row.gender, re.I)
            matches_f = re.findall(r"\b(female|woman|f)\b", row.gender, re.I)
            if matches_m or matches_f:
                sexes["male"] += len(matches_m)
                sexes["female"] += len(matches_f)
            elif not row.gender:
                sexes[""] += 1
            else:
                sexes["other"] += 1

            # This is largely junk, because people put jokes or expressions of surprise, which can
            # only reasonably be categorised as "other". Next time, we should use an autocomplete,
            # explain why we're collecting this information, and separate "other" from "unknown".
            matches_white = re.findall(
                r"\b(white|caucasian|wasp)\b", row.ethnicity, re.I
            )
            # People really like putting their heritage, which gives another data point or two.
            matches_anglo = re.findall(
                r"\b(british|english|irish|scottish|welsh|american|australian|canadian|zealand|nz)\b",
                row.ethnicity,
                re.I,
            )
            if matches_white or matches_anglo:
                if matches_white and matches_anglo:
                    ethnicities["both"] += 1
                elif matches_white:
                    ethnicities["white"] += 1
                elif matches_anglo:
                    ethnicities["anglosphere"] += 1
            elif not row.ethnicity:
                ethnicities[""] += 1
            else:
                ethnicities["other"] += 1

        ages.update(bucketise(valid_ages, [0, 15, 25, 35, 45, 55, 65]))

        data = {
            "private": {
                "diversity": {"age": ages, "sex": sexes, "ethnicity": ethnicities}
            },
            "tables": ["diversity"],
        }

        return data
