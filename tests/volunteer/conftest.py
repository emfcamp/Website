import warnings

import pytest
from sqlalchemy.exc import SAWarning

from models.volunteer.volunteer import Volunteer


@pytest.fixture(autouse=True)
def session(db, user):
    tx = db.session.begin_nested()
    yield

    with warnings.catch_warnings(action="error", category=SAWarning):
        try:
            tx.rollback()
        except SAWarning as err:
            if "transaction already deassociated" not in str(err):
                # The transaction has already been rolled back.
                raise

    # The User object is persistent throughout a module so we need
    # to expire it so that changes get reverted. Arguably we should
    # just create a new user for each test run but I'm not sure of the
    # wider implications for that.
    db.session.expire(user)


@pytest.fixture
def volunteer(db, user):
    volunteer = Volunteer.query.filter(Volunteer.user_id == user.id).one_or_none()
    if volunteer is None:
        volunteer = Volunteer(user=user)
        db.session.add(volunteer)
        user.grant_permission("volunteer:user")
        db.session.flush()

    return volunteer
