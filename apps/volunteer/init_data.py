from pathlib import Path
from typing import Any

from flask import current_app as app
from yaml import safe_load


def load_from_yaml(path_glob: str) -> list[dict[str, Any]]:
    """Loads all YAML files from the passed path glob."""
    items = []

    for path in Path(app.root_path).glob(path_glob):
        with open(path, "r") as file:
            items.append(safe_load(file))

    return items


def load_initial_venues() -> list[dict[str, Any]]:
    """Loads venue data."""
    return load_from_yaml("apps/volunteer/data/venues/*.yml")


def load_initial_roles() -> list[dict[str, Any]]:
    """Loads role data."""
    return load_from_yaml("apps/volunteer/data/roles/*.yml")
