from models.scheduled_task import execute_scheduled_tasks


def test_scheduled_tasks(app):
    execute_scheduled_tasks(force=True)
