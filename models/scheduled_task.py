""" A simple job scheduler, because everything else is too complicated.

    To schedule a task:
    ```
    from models.scheduled_task import scheduled_task

    @scheduled_task(minutes=30)
    def my_function():
        ...
    ```

    The return value or any exception raised is recorded.

    Tasks are run in a separate process by the `flask periodic` command
    and do not run by default in dev. This process is run by cron so
    granularity is no better than a few minutes.
"""
import pendulum
import logging
from functools import wraps

from main import db
from . import BaseModel

tasks = []
log = logging.getLogger(__name__)


class ScheduledTask(object):
    def __init__(self, func, duration):
        self.func = func
        self.duration = duration

    @property
    def name(self):
        return self.func.__module__ + "." + self.func.__name__

    def __repr__(self):
        return f"<ScheduledTask: {self.name}, every {self.duration}>"


class ScheduledTaskResult(BaseModel):
    __tablename__ = "scheduled_task_result"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    start_time = db.Column(db.DateTime(True), nullable=False)
    duration = db.Column(db.Interval, nullable=False)
    result = db.Column(db.JSON, nullable=False)

    def __init__(self, job_name):
        self.name = job_name
        self.start_time = pendulum.now()
        self.result = {}

    def finish(self):
        self.duration = pendulum.now() - self.start_time

    @classmethod
    def get_latest_run(cls, name, session=None):
        if session is None:
            session = db.session
        return (
            session.query(cls)
            .filter_by(name=name)
            .order_by(ScheduledTaskResult.start_time.desc())
            .limit(1)
            .one_or_none()
        )

    @classmethod
    def cleanup(cls, session=None):
        """Delete results older than a week"""
        if session is None:
            session = db.session
        session.query(cls).filter(
            cls.start_time < pendulum.now() - pendulum.duration(days=7)
        ).delete()


def scheduled_task(**kwargs):
    def decorator(f):
        duration = pendulum.duration(**kwargs)
        if duration < pendulum.duration(minutes=1):
            raise ValueError("Please provide a duration greater than 1 minute")
        tasks.append(ScheduledTask(f, duration))

        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, **kwargs)

        return wrapper

    return decorator


def execute_scheduled_tasks(force=False):
    # Create a new session, so tasks calling commit don't free our lock
    session = db.create_scoped_session()

    # Take an exclusive lock on the ScheduledTaskResult table to prevent tasks colliding
    session.execute(f"LOCK TABLE {ScheduledTaskResult.__tablename__} IN EXCLUSIVE MODE")

    tasks_to_run = []
    if force:
        tasks_to_run += tasks
    else:
        for task in tasks:
            res = ScheduledTaskResult.get_latest_run(task.name, session)
            if res is None or res.start_time + task.duration < pendulum.now():
                tasks_to_run.append(task)

    log.info("Running %s periodic tasks...", len(tasks_to_run))
    for task in tasks_to_run:
        log.info("Running %s", task.name)
        result = ScheduledTaskResult(task.name)
        try:
            result.result["returnval"] = task.func()

        except Exception as e:
            log.exception(f"Exception in {task.name}: {repr(e)}")
            result.result["exception"] = repr(e)

        # Clean up the main session whatever happens
        db.session.rollback()

        result.finish()
        session.add(result)

    ScheduledTaskResult.cleanup(session)
    session.commit()
    log.info("Tasks complete.")
