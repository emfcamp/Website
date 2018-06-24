" PyTest Config. This contains global-level pytest fixtures. "
import os
import os.path
import pytest
import shutil
from models.user import User
from main import create_app, db as db_obj, Mail
from utils import CreateBankAccounts, CreateTickets


@pytest.fixture(scope="module")
def app():
    """ Fixture to provide an instance of the app.
        This will also create a Flask app_context and tear it down.

        This fixture is scoped to the module level to avoid too much
        Postgres teardown/creation activity which is slow.
    """
    if 'SETTINGS_FILE' not in os.environ:
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
        os.environ['SETTINGS_FILE'] = os.path.join(root, 'config', 'test.cfg')

    tmpdir = os.environ.get('TMPDIR', '/tmp')
    prometheus_dir = os.path.join(tmpdir, 'emf_test_prometheus')
    os.environ['prometheus_multiproc_dir'] = prometheus_dir

    if os.path.exists(prometheus_dir):
        shutil.rmtree(prometheus_dir)
    if not os.path.exists(prometheus_dir):
        os.mkdir(prometheus_dir)

    app = create_app()

    with app.app_context():
        try:
            db_obj.session.close()
        except:
            pass

        db_obj.drop_all()

        db_obj.create_all()
        CreateBankAccounts().run()
        CreateTickets().run()

        yield app

        db_obj.session.close()
        db_obj.drop_all()


@pytest.fixture
def client(app):
    " Yield a test HTTP client for the app "
    yield app.test_client()


@pytest.fixture
def db(app):
    " Yield the DB object "
    yield db_obj


@pytest.fixture
def request_context(app):
    " Run the test in an app request context "
    with app.test_request_context('/') as c:
        yield c


@pytest.fixture
def user(db):
    " Yield a test user. Note that this user will be identical across all tests in a module. "
    email = 'test_user@test.invalid'
    user = User.query.filter(User.email == email).one_or_none()
    if not user:
        user = User(email, 'Test User')
        db.session.add(user)
        db.session.commit()

    yield user


@pytest.fixture
def outbox(app):
    " Capture mail and yield the outbox. "
    mail_obj = Mail()
    with mail_obj.record_messages() as outbox:
        yield outbox
