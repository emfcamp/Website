from datetime import datetime
from pathlib import Path
from typing import Any

from flask import current_app as app
from pendulum import parse
from yaml import safe_load

from apps.config import config
from apps.volunteer.shift_list import get_shift_list
from main import db
from models.volunteer.role import Role, Team
from models.volunteer.shift import Shift, ShiftTemplate, event_tz
from models.volunteer.venue import VolunteerVenue


def load_yaml_config() -> None:
    for t in load_from_yaml("apps/volunteer/data/teams/*.yml"):
        team = Team.from_dict(t)
        app.logger.info(f"Adding team {team}")
        db.session.add(team)

        for r in load_from_yaml(f"apps/volunteer/data/roles/{t['slug'].replace('-', '_')}/*.yml"):
            role = Role.from_dict(r)
            role.team = team
            app.logger.info(f"Adding role {role}")
            db.session.add(role)

    for v in load_from_yaml("apps/volunteer/data/venues/*.yml"):
        venue = VolunteerVenue.from_dict(v)
        app.logger.info(f"Adding venue {venue}")
        db.session.add(venue)


def seed_shift_templates():
    """Turns seed data from app/volunteer/shifts/*.py into ShiftTemplates.

    This is intended to be a one time migration, once this migration has been performed
    in production this code can be deleted and future seeding driven from post-event
    exports to ensure we reflect the final configuration. Also to be deleted are:

    - apps/volunteer/shifts/
    - apps/volunteer/event_date.py
    """
    load_yaml_config()
    shift_list = get_shift_list()
    for shift_role in shift_list:
        role = Role.get_by_slug(shift_role)
        if role is None:
            app.logger.error(f"Unknown role: {shift_role}")
            continue

        for shift_venue in shift_list[shift_role]:
            venue = VolunteerVenue.get_by_slug(shift_venue)
            if venue is None:
                app.logger.error(f"Unknown venue: {shift_venue}")
                continue

            for shift_range in shift_list[shift_role][shift_venue]:
                first = event_tz.localize(datetime.strptime(shift_range["first"], "%Y-%m-%d %H:%M:%S"))
                final = event_tz.localize(datetime.strptime(shift_range["final"], "%Y-%m-%d %H:%M:%S"))

                delta = first.date() - config.event_start.date()
                # Day 0 is the day before event_start.
                event_day = delta.days + 1

                template = ShiftTemplate(
                    role_id=role.id,
                    venue_id=venue.id,
                    event_day=event_day,
                    start_time=first.time(),
                    end_time=final.time(),
                    duration=shift_range.get("duration", 120),
                    changeover_time=shift_range.get("changeover", 15),
                    min_needed=shift_range["min"],
                    max_needed=shift_range["max"],
                    notes=shift_range.get("notes", ""),
                )
                db.session.add(template)

    db.session.commit()


def shifts():
    load_yaml_config()
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
                    first=parse(shift_range["first"], tz=event_tz),
                    final=parse(shift_range["final"], tz=event_tz),
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
            item: dict[str, Any] = safe_load(file) | {"slug": path.stem.replace("_", "-")}
            items.append(item)

    return items
