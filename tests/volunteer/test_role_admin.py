"""Tests for volunteer role admin permissions."""

from unittest.mock import MagicMock, patch

import pytest

from apps.volunteer.choose_roles import role_admin_required
from models.volunteer.role import Role, RoleAdmin, Team, TeamAdmin


@pytest.fixture(autouse=True)
def session(db):
    """Wrap each test in a transaction which gets rolled back on completion."""
    with db.session.begin():
        yield
        db.session.rollback()


@pytest.fixture()
def team(db):
    t = Team(name="Test Team", slug="test-team")
    db.session.add(t)
    return t


@pytest.fixture()
def role(db, team):
    r = Role(name="Test Role", team=team)
    db.session.add(r)
    return r


@pytest.fixture()
def other_role(db, team):
    r = Role(name="Other Test Role", team=team)
    db.session.add(r)
    return r


def test_administered_role_ids_empty(volunteer, db):
    assert volunteer.administered_role_ids == set()


def test_administered_role_ids_direct(volunteer, role, db):
    ra = RoleAdmin(volunteer=volunteer, role=role)
    db.session.add(ra)
    db.session.refresh(volunteer)
    assert role.id in volunteer.administered_role_ids


def test_administered_role_ids_via_team(volunteer, team, role, other_role, db):
    ta = TeamAdmin(volunteer=volunteer, team=team)
    db.session.add(ta)
    db.session.refresh(volunteer)
    ids = volunteer.administered_role_ids
    assert role.id in ids
    assert other_role.id in ids


def test_administered_role_ids_union(volunteer, team, role, other_role, db):
    ra = RoleAdmin(volunteer=volunteer, role=role)
    ta = TeamAdmin(volunteer=volunteer, team=team)
    db.session.add_all([ra, ta])
    db.session.refresh(volunteer)
    ids = volunteer.administered_role_ids
    assert role.id in ids
    assert other_role.id in ids


def test_is_volunteer_admin_false(volunteer, db):
    db.session.refresh(volunteer)
    assert not volunteer.is_volunteer_admin


def test_is_volunteer_admin_via_role(volunteer, role, db):
    ra = RoleAdmin(volunteer=volunteer, role=role)
    db.session.add(ra)
    db.session.refresh(volunteer)
    assert volunteer.is_volunteer_admin


def test_is_volunteer_admin_via_team(volunteer, team, db):
    ta = TeamAdmin(volunteer=volunteer, team=team)
    db.session.add(ta)
    db.session.refresh(volunteer)
    assert volunteer.is_volunteer_admin


def _invoke(role_id, volunteer):
    """Call a role_admin_required-decorated view, return (was_called, abort_mock)."""
    called = []

    @role_admin_required
    def view(role_id):
        called.append(role_id)
        return "ok"

    mock_app = MagicMock()
    with (
        patch("apps.volunteer.choose_roles.current_user", volunteer.user),
        patch("apps.volunteer.choose_roles.abort") as mock_abort,
        patch("apps.volunteer.choose_roles.app", mock_app),
    ):
        view(role_id)

    return called, mock_abort


def test_role_admin_required_denies_non_admin(volunteer, db):
    db.session.refresh(volunteer)
    called, mock_abort = _invoke(42, volunteer)
    mock_abort.assert_called_once_with(404)
    assert called == []


def test_role_admin_required_allows_direct_role_admin(volunteer, role, db):
    ra = RoleAdmin(volunteer=volunteer, role=role)
    db.session.add(ra)
    db.session.refresh(volunteer)
    called, mock_abort = _invoke(role.id, volunteer)
    mock_abort.assert_not_called()
    assert called == [role.id]
    db.session.delete(ra)


def test_role_admin_required_allows_team_admin(volunteer, team, role, db):
    ta = TeamAdmin(volunteer=volunteer, team=team)
    db.session.add(ta)
    db.session.refresh(volunteer)
    called, mock_abort = _invoke(role.id, volunteer)
    mock_abort.assert_not_called()
    assert called == [role.id]
    db.session.delete(ta)


def test_role_admin_required_allows_volunteer_admin_permission(volunteer, role, db):
    volunteer.user.grant_permission("volunteer:admin")
    db.session.refresh(volunteer)
    called, mock_abort = _invoke(role.id, volunteer)
    mock_abort.assert_not_called()
    assert called == [role.id]


def test_role_admin_required_allows_volunteer_manager_permission(volunteer, role, db):
    volunteer.user.grant_permission("volunteer:manager")
    db.session.refresh(volunteer)
    called, mock_abort = _invoke(role.id, volunteer)
    mock_abort.assert_not_called()
    assert called == [role.id]


def test_role_admin_required_unauthenticated(volunteer, db):
    @role_admin_required
    def view(role_id):
        return "ok"

    mock_app = MagicMock()
    mock_user = MagicMock(is_authenticated=False)
    with (
        patch("apps.volunteer.choose_roles.current_user", mock_user),
        patch("apps.volunteer.choose_roles.app", mock_app),
    ):
        view(42)
        mock_app.login_manager.unauthorized.assert_called_once()
