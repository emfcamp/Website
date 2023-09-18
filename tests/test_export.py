from apps.base.tasks_export import get_export_data


def test_export(app):
    """Test that the export succeeds without error."""
    export = list(get_export_data())
    assert len(export) > 0
