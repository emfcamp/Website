from datetime import date, datetime
from decimal import Decimal
import simplejson
import os

from flask import current_app as app
from flask_script import Command, Option
from sqlalchemy_continuum.utils import version_class, is_versioned

from main import db


class ExportDB(Command):
    """
    Dump public and private data, run as a last step before wiping the DB after an event

    Model classes should implement get_export_data, which returns a dict with keys:
        public   Public data to save in git
        private  Private data that should be stored for a limited amount of time
        tables   Tables this method exported, used to sanity check the export process

    Alternatively, add __export_data__ = False to a class to state that get_export_data
    shouldn't be called, and that its associated table doesn't need to be checked.
    """
    def run(self):
        # As we go, we check against the list of all tables, in case we forget about some
        # new object type (e.g. association table).

        # Exclude tables we know will never be exported, such as fixtures.
        fixtures = ['bank_account', 'permission', 'ticket_price', 'ticket_type', 'venue']
        ignore = ['alembic_version', 'feature_flag', 'site_state']
        needs_work = []

        all_model_classes = {cls for cls in db.Model._decl_class_registry.values()
                             if isinstance(cls, type) and issubclass(cls, db.Model)}

        all_version_classes = {version_class(c) for c in all_model_classes if is_versioned(c)}

        seen_model_classes = set()
        remaining_tables = set(db.metadata.tables)

        year = datetime.utcnow().year
        path = os.path.join('exports', str(year))
        for dirname in ['public', 'private']:
            os.makedirs(os.path.join(path, dirname), exist_ok=True)

        for model_class in all_model_classes:
            if model_class in seen_model_classes:
                continue

            seen_model_classes.add(model_class)

            table = model_class.__table__.name
            model = model_class.__name__

            if table in fixtures + ignore:
                app.logger.debug('Ignoring %s', model)
                remaining_tables.remove(table)
                continue

            if not getattr(model_class, '__export_data__', True):
                # We don't remove the version table, as we want
                # to be explicit about chucking away edit stats
                app.logger.debug('Skipping %s', model)
                remaining_tables.remove(table)
                continue

            if model_class in all_version_classes:
                # Version tables are explicitly dumped by their parents,
                # as they don't make sense to be exported on their own
                app.logger.debug('Ignoring version model %s', model)
                continue

            if hasattr(model_class, 'get_export_data'):
                try:
                    export = model_class.get_export_data()
                    for dirname in ['public', 'private']:
                        if dirname in export:
                            filename = os.path.join(path, dirname, '{}.json'.format(model))
                            simplejson.dump(export[dirname], open(filename, 'w'), indent=4, sort_keys=True)
                            app.logger.info('Exported data from %s to %s', model, filename)

                except Exception as e:
                    app.logger.error('Error exporting %s', model)
                    raise

                exported_tables = export.get('tables', [table])
                remaining_tables -= set(exported_tables)

        if remaining_tables:
            app.logger.warning('Remaining tables: %s', ', '.join(remaining_tables))

        data = {
            'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
            'remaining_tables': sorted(list(remaining_tables))
        }
        filename = os.path.join(path, 'export.json')
        simplejson.dump(data, open(filename, 'w'), indent=4, sort_keys=True)

        app.logger.info('Export complete, summary written to %s', filename)

