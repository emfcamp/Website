from apps.base.tasks_export import get_export_data

# from apps.base.dev.fake import FakeDataGenerator


def test_export(app):
    """Test that the export succeeds without error."""
    # Generating fake data will improve coverage but takes ages
    #
    # fdg = FakeDataGenerator()
    # fdg.run()
    export = list(get_export_data())
    assert len(export) > 0
