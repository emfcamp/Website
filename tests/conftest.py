"PyTest Config. This contains global-level pytest fixtures."

import datetime
import os
import os.path
import shutil

import pytest
from flask_mailman import Mail
from freezegun import freeze_time
from sqlalchemy import text

from apps.base.dev.tasks import create_bank_accounts
from apps.tickets.tasks import create_product_groups
from main import create_app
from main import db as db_obj
from models.site_state import SiteState
from models.user import User


@pytest.fixture(scope="module")
def app():
    """Fixture to provide an instance of the app.
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
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = prometheus_dir

    if os.path.exists(prometheus_dir):
        shutil.rmtree(prometheus_dir)
    if not os.path.exists(prometheus_dir):
        os.mkdir(prometheus_dir)

    # We don't support events which span the year-end, so generate a date next year.
    now = datetime.datetime.now()
    fake_event_start = datetime.datetime(year=now.year + 1, month=6, day=2, hour=8)
    config_override = {
        "EVENT_START": fake_event_start.isoformat(),
        "EVENT_END": (fake_event_start + datetime.timedelta(days=4)).isoformat(),
    }

    fake_now = fake_event_start - datetime.timedelta(weeks=10)

    if cache:
        config_override["CACHE_TYPE"] = "flask_caching.backends.SimpleCache"

    app = create_app(dev_server=True, config_override=config_override)

    # Freeze time at fake_now
    freezer = freeze_time(fake_now)
    freezer.start()
    with app.app_context():
        try:
            db_obj.session.close()
        except Exception:
            pass

        db_obj.drop_all()

        # We're not using migrations here so we have to create the extension manually
        db_obj.session.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        db_obj.session.commit()
        db_obj.session.close()

        db_obj.create_all()
        create_bank_accounts()
        create_product_groups()

        state = SiteState("site_state", "sales")
        db_obj.session.add(state)

        yield app

        # For unclear reasons we're picking up an `alembic_version` table even though
        # we're not using Alembic here. Drop it to avoid confusing future users of the test database.
        db_obj.session.rollback()
        db_obj.session.execute(text("DROP TABLE IF EXISTS alembic_version"))
        db_obj.session.commit()

        db_obj.session.close()

        # Allow keeping test data for debugging via test app
        # Set KEEP_TEST_DB=1 to preserve data after tests
        if not os.environ.get("KEEP_TEST_DB"):
            db_obj.drop_all()
    freezer.stop()


@pytest.fixture
def client(app):
    "Yield a test HTTP client for the app"
    yield app.test_client()


@pytest.fixture(scope="module")
def db(app):
    "Yield the DB object"
    yield db_obj


@pytest.fixture
def request_context(app):
    "Run the test in an app request context"
    with app.test_request_context("/") as c:
        yield c


@pytest.fixture(scope="module")
def user(db):
    "Yield a test user. Note that this user will be identical across all tests in a module."
    email = "test_user@example.com"
    user = User.query.filter(User.email == email).one_or_none()
    if not user:
        user = User(email, "Test User")
        db.session.add(user)
        db.session.commit()

    yield user


@pytest.fixture
def outbox(app):
    "Yield the outbox"
    mail = Mail(app)
    mail.get_connection()
    yield mail.outbox


# ============================================================================
# CfP E2E Test Fixtures
# ============================================================================


@pytest.fixture
def cli_runner(app):
    """Flask CLI test runner for testing ./flask commands"""
    yield app.test_cli_runner()


@pytest.fixture(scope="module")
def cfp_admin_user(db):
    """User with cfp_admin permission (cfp_admin@test.invalid)"""
    email = "cfp_admin@test.invalid"
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email, "Test CFP Admin")
        user.grant_permission("cfp_admin")
        db.session.add(user)
        db.session.commit()
    return user


@pytest.fixture(scope="module")
def cfp_anonymiser_user(db):
    """User with cfp_anonymiser permission"""
    email = "anonymiser@test.invalid"
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email, "Test Anonymiser")
        user.grant_permission("cfp_anonymiser")
        db.session.add(user)
        db.session.commit()
    return user


@pytest.fixture(scope="module")
def cfp_reviewers(db):
    """10 reviewers with cfp_reviewer permission (reviewer0-9@test.invalid)"""
    reviewers = []
    for i in range(10):
        email = f"reviewer{i}@test.invalid"
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email, f"Reviewer {i}")
            user.grant_permission("cfp_reviewer")
            db.session.add(user)
        reviewers.append(user)
    db.session.commit()
    return reviewers


@pytest.fixture(scope="module")
def e2e_speakers(db):
    """Create unique speaker users for each proposal to avoid double-booking conflicts"""
    speakers = []
    for i in range(60):
        email = f"speaker{i}@test.invalid"
        user = User.query.filter_by(email=email).first()
        if not user:
            user = User(email, f"Speaker {i}")
            db.session.add(user)
        speakers.append(user)
    db.session.commit()
    return speakers


def login_user_to_client(client, user):
    """Log in user via BYPASS_LOGIN URL: /login/email@test.invalid"""
    response = client.get(f"/login/{user.email}", follow_redirects=True)
    return response
