import json
import os
from collections.abc import Iterable
from typing import Any, cast

import click
from flask import current_app as app
from sqlalchemy.orm.decl_api import DeclarativeBase
from sqlalchemy_continuum.utils import is_versioned, version_class

from apps.common.json_export import ExportEncoder
from main import db
from models import event_year, naive_utcnow

from . import base


def get_export_data(table_filter: str | None = None) -> Iterable[tuple[str, Any]]:
    """Export data to archive using the `get_export_data` method in the model class."""
    # As we go, we check against the list of all tables, in case we forget about some
    # new object type (e.g. association table).

    # Exclude tables we know will never be exported

    ignore = ["alembic_version", "transaction"]

    all_model_classes = {
        cls
        for cls in cast(type[DeclarativeBase], db.Model).registry._class_registry.values()
        if isinstance(cls, type) and issubclass(cls, db.Model)
    }

    all_version_classes = {version_class(c) for c in all_model_classes if is_versioned(c)}

    seen_model_classes = set()
    remaining_tables = set(db.metadata.tables)

    for model_class in sorted(all_model_classes, key=lambda c: c.__name__):
        if model_class in seen_model_classes:
            continue

        seen_model_classes.add(model_class)

        table = model_class.__table__.name  # type: ignore[attr-defined]
        model = model_class.__name__

        if table_filter and table != table_filter:
            continue

        if table in ignore:
            app.logger.debug("Ignoring %s", model)
            remaining_tables.remove(table)
            continue

        if not getattr(model_class, "__export_data__", True):
            # We don't remove the version table, as we want
            # to be explicit about chucking away edit stats
            app.logger.debug("Skipping %s", model)
            remaining_tables.remove(table)
            continue

        if model_class in all_version_classes:
            # Version tables are explicitly dumped by their parents,
            # as they don't make sense to be exported on their own
            app.logger.debug("Ignoring version model %s", model)
            continue

        if hasattr(model_class, "get_export_data"):
            try:
                export = model_class.get_export_data()
                yield model, export
            except Exception:
                app.logger.error("Error exporting %s", model)
                raise

            exported_tables = export.get("tables", [table])
            remaining_tables -= set(exported_tables)

    if remaining_tables and not table_filter:
        app.logger.warning("Remaining tables: %s", ", ".join(remaining_tables))
    elif table_filter in remaining_tables:
        app.logger.warning("Table %s not exported", table_filter)


@base.cli.command("export")
@click.option("--stdout", is_flag=True, help="Print to stdout rather than write to disk")
@click.argument("table", required=False)
def export_db(stdout, table):
    """Export data from the DB to disk.

    This command is run as a last step before wiping the DB after an event, to export
    all the data we want to save. It saves a private and a public export to the
    exports directory.

    Model classes should implement get_export_data, which returns a dict with keys:

        public   Public data to save in git

        private  Private data that should be stored for a limited amount of time

        tables   Tables this method exported, used to sanity check the export process

    Alternatively, add __export_data__ = False to a class to state that get_export_data
    shouldn't be called, and that its associated table doesn't need to be checked.
    """

    year = event_year()
    path = os.path.join("exports", str(year))
    for dirname in ["public", "private"]:
        os.makedirs(os.path.join(path, dirname), exist_ok=True)

    for model, export in get_export_data(table):
        for dirname in ["public", "private"]:
            if dirname in export:
                filename = os.path.join(path, dirname, f"{model}.json")
                try:
                    if stdout:
                        app.logger.info(json.dumps(export[dirname]))
                    else:
                        with open(filename, "w") as f:
                            json.dump(
                                export[dirname],
                                f,
                                indent=4,
                                cls=ExportEncoder,
                            )
                except Exception as e:
                    app.logger.exception("Error encoding export for %s", model)
                    raise click.Abort() from e
                app.logger.info("Exported data from %s to %s", model, filename)

    data = {
        "timestamp": naive_utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    }
    filename = os.path.join(path, "export.json")

    if stdout:
        app.logger.info(json.dumps(data))
    else:
        with open(filename, "w") as f:
            json.dump(data, f, indent=4, cls=ExportEncoder)

    if table:
        return

    with app.test_client() as client:
        for file_type in ["frab", "json", "ics"]:
            url = f"/schedule/{year}.{file_type}"
            dest_path = os.path.join(path, "public", f"schedule.{file_type}")
            response = client.get(url)
            if response.status_code != 200:
                app.logger.error("Error fetching schedule from %s: %s", url, response.status)
                raise click.Abort()
            with open(dest_path, "wb") as f:
                f.write(response.data)
            app.logger.info("Fetched schedule from %s to %s", url, dest_path)

    app.logger.info("Export complete, summary written to %s", filename)
