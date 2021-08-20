" PyTest Config. This contains global-level pytest fixtures. "
import os
import os.path
import pytest
import shutil
import datetime
from sqlalchemy import text
from models.user import User
from main import create_app, db as db_obj, Mail
from apps.base.tasks_banking import create_bank_accounts
from apps.tickets.tasks import create_product_groups


@pytest.fixture(scope="module")
def app():
    """ Fixture to provide an instance of the app.
        This will also create a Flask app_context and tear it down.

        This fixture is scoped to the module level to avoid too much
        Postgres teardown/creation activity which is slow.
    """
    yield from app_factory(False)


@pytest.fixture(scope="module")
def app_with_cache():
    yield from app_factory(True)


def app_factory(cache):
    if "SETTINGS_FILE" not in os.environ:
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        os.environ["SETTINGS_FILE"] = os.path.join(root, "config", "test.cfg")

    tmpdir = os.environ.get("TMPDIR", "/tmp")
    prometheus_dir = os.path.join(tmpdir, "emf_test_prometheus")
    os.environ["prometheus_multiproc_dir"] = prometheus_dir

    if os.path.exists(prometheus_dir):
        shutil.rmtree(prometheus_dir)
    if not os.path.exists(prometheus_dir):
        os.mkdir(prometheus_dir)

    #  For test purposes we're perpetually 2 weeks into ticket sales and 10 weeks before the event.
    fake_event_start = datetime.datetime.now() + datetime.timedelta(weeks=10)
    config_override = {
        "SALES_START": (
            datetime.datetime.now() - datetime.timedelta(weeks=2)
        ).isoformat(),
        "EVENT_START": fake_event_start.isoformat(),
        "EVENT_END": (fake_event_start + datetime.timedelta(days=4)).isoformat(),
    }
    if cache:
        config_override["CACHE_TYPE"] = "simple"

    app = create_app(dev_server=True, config_override=config_override)

    with app.app_context():
        try:
            db_obj.session.close()
        except:
            pass

        db_obj.drop_all()

        # We're not using migrations here so we have to create the extension manually
        db_obj.session.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        db_obj.session.commit()
        db_obj.session.close()

        db_obj.create_all()
        create_bank_accounts()
        create_product_groups()

        yield app

        db_obj.session.close()
        db_obj.drop_all()


@pytest.fixture
def client(app):
    " Yield a test HTTP client for the app "
    yield app.test_client()


@pytest.fixture(scope="module")
def db(app):
    " Yield the DB object "
    yield db_obj


@pytest.fixture
def request_context(app):
    " Run the test in an app request context "
    with app.test_request_context("/") as c:
        yield c


@pytest.fixture(scope="module")
def user(db):
    " Yield a test user. Note that this user will be identical across all tests in a module. "
    email = "test_user@example.com"
    user = User.query.filter(User.email == email).one_or_none()
    if not user:
        user = User(email, "Test User")
        db.session.add(user)
        db.session.commit()

    yield user


@pytest.fixture
def outbox(app):
    " Capture mail and yield the outbox. "
    mail_obj = Mail()
    with mail_obj.record_messages() as outbox:
        yield outbox
