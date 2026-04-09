from pathlib import Path
from typing import Any

from flask import current_app as app
from pendulum import parse
from yaml import safe_load

from apps.volunteer.shift_list import get_shift_list
from main import db
from models.volunteer.role import Role, Team
from models.volunteer.shift import Shift
from models.volunteer.venue import VolunteerVenue


def shifts():
    for t in load_from_yaml("apps/volunteer/data/teams/*.yml"):
        team = Team.from_dict(t)
        app.logger.info(f"Adding team {team}")
        db.session.add(team)

        for r in load_from_yaml(f"apps/volunteer/data/roles/{t['slug']}/*.yml"):
            role = Role.from_dict(r)
            role.team = team
            app.logger.info(f"Adding role {role}")
            db.session.add(role)

    for v in load_from_yaml("apps/volunteer/data/venues/*.yml"):
        venue = VolunteerVenue.from_dict(v)
        app.logger.info(f"Adding venue {venue}")
        db.session.add(venue)

    shift_list = get_shift_list()

    for shift_role in shift_list:
        role = Role.get_by_slug(shift_role)
        if role is None:
            app.logger.error(f"Unknown role: {shift_role}")
            continue

        if role.shifts:
            app.logger.info(f"Skipping making shifts for role: {role.name}")
            continue

        for shift_venue in shift_list[shift_role]:
            venue = VolunteerVenue.get_by_slug(shift_venue)
            if venue is None:
                app.logger.error(f"Unknown venue: {shift_venue}")
                continue

            for shift_range in shift_list[shift_role][shift_venue]:
                shifts = Shift.generate_for(
                    role=role,
                    venue=venue,
                    first=parse(shift_range["first"]),
                    final=parse(shift_range["final"]),
                    min=shift_range["min"],
                    max=shift_range["max"],
                    base_duration=shift_range.get("base_duration", 120),
                    changeover=shift_range.get("changeover", 15),
                )
                for s in shifts:
                    db.session.add(s)

    db.session.commit()


def load_from_yaml(path_glob: str) -> list[dict[str, Any]]:
    """Loads all YAML files from the passed path glob."""
    items = []

    for path in Path(app.root_path).glob(path_glob):
        with open(path) as file:
            item: dict[str, Any] = safe_load(file) | {"slug": path.stem}
            items.append(item)

    return items
