"""Tests for volunteer role admin permissions."""

from unittest.mock import MagicMock, patch

import pytest

from apps.volunteer.choose_roles import role_admin_required
from models.user import User
from models.volunteer.role import Role, RoleAdmin, Team, TeamAdmin


@pytest.fixture(scope="module")
def team(db):
    t = Team(name="Test Team", slug="test-team")
    db.session.add(t)
    db.session.commit()
    return t


@pytest.fixture(scope="module")
def role(db, team):
    r = Role(name="Test Role", team=team)
    db.session.add(r)
    db.session.commit()
    return r


@pytest.fixture(scope="module")
def other_role(db, team):
    r = Role(name="Other Test Role", team=team)
    db.session.add(r)
    db.session.commit()
    return r


@pytest.fixture(scope="module")
def admin_user(db):
    u = User("role_admin@example.com", "Role Admin")
    db.session.add(u)
    db.session.commit()
    return u


# ── administered_role_ids ──────────────────────────────────────────────────────


def test_administered_role_ids_empty(admin_user, db):
    db.session.refresh(admin_user)
    assert admin_user.administered_role_ids == set()


def test_administered_role_ids_direct(admin_user, role, db):
    ra = RoleAdmin(user=admin_user, role=role)
    db.session.add(ra)
    db.session.flush()
    db.session.refresh(admin_user)
    assert role.id in admin_user.administered_role_ids
    db.session.delete(ra)
    db.session.commit()


def test_administered_role_ids_via_team(admin_user, team, role, other_role, db):
    ta = TeamAdmin(user=admin_user, team=team)
    db.session.add(ta)
    db.session.flush()
    db.session.refresh(admin_user)
    ids = admin_user.administered_role_ids
    assert role.id in ids
    assert other_role.id in ids
    db.session.delete(ta)
    db.session.commit()


def test_administered_role_ids_union(admin_user, team, role, other_role, db):
    ra = RoleAdmin(user=admin_user, role=role)
    ta = TeamAdmin(user=admin_user, team=team)
    db.session.add_all([ra, ta])
    db.session.flush()
    db.session.refresh(admin_user)
    ids = admin_user.administered_role_ids
    assert role.id in ids
    assert other_role.id in ids
    db.session.delete(ra)
    db.session.delete(ta)
    db.session.commit()


# ── is_volunteer_admin ─────────────────────────────────────────────────────────


def test_is_volunteer_admin_false(admin_user, db):
    db.session.refresh(admin_user)
    assert not admin_user.is_volunteer_admin


def test_is_volunteer_admin_via_role(admin_user, role, db):
    ra = RoleAdmin(user=admin_user, role=role)
    db.session.add(ra)
    db.session.flush()
    db.session.refresh(admin_user)
    assert admin_user.is_volunteer_admin
    db.session.delete(ra)
    db.session.commit()


def test_is_volunteer_admin_via_team(admin_user, team, db):
    ta = TeamAdmin(user=admin_user, team=team)
    db.session.add(ta)
    db.session.flush()
    db.session.refresh(admin_user)
    assert admin_user.is_volunteer_admin
    db.session.delete(ta)
    db.session.commit()


# ── role_admin_required decorator ─────────────────────────────────────────────


def _invoke(role_id, user):
    """Call a role_admin_required-decorated view, return (was_called, abort_mock)."""
    called = []

    @role_admin_required
    def view(role_id):
        called.append(role_id)
        return "ok"

    mock_app = MagicMock()
    with (
        patch("apps.volunteer.choose_roles.current_user", user),
        patch("apps.volunteer.choose_roles.abort") as mock_abort,
        patch("apps.volunteer.choose_roles.app", mock_app),
    ):
        view(role_id)

    return called, mock_abort


def test_role_admin_required_denies_non_admin(admin_user, db):
    db.session.refresh(admin_user)
    called, mock_abort = _invoke(42, admin_user)
    mock_abort.assert_called_once_with(404)
    assert called == []


def test_role_admin_required_allows_direct_role_admin(admin_user, role, db):
    ra = RoleAdmin(user=admin_user, role=role)
    db.session.add(ra)
    db.session.flush()
    db.session.refresh(admin_user)
    called, mock_abort = _invoke(role.id, admin_user)
    mock_abort.assert_not_called()
    assert called == [role.id]
    db.session.delete(ra)
    db.session.commit()


def test_role_admin_required_allows_team_admin(admin_user, team, role, db):
    ta = TeamAdmin(user=admin_user, team=team)
    db.session.add(ta)
    db.session.flush()
    db.session.refresh(admin_user)
    called, mock_abort = _invoke(role.id, admin_user)
    mock_abort.assert_not_called()
    assert called == [role.id]
    db.session.delete(ta)
    db.session.commit()


def test_role_admin_required_allows_volunteer_admin_permission(admin_user, role, db):
    admin_user.grant_permission("volunteer:admin")
    db.session.commit()
    db.session.refresh(admin_user)
    called, mock_abort = _invoke(role.id, admin_user)
    mock_abort.assert_not_called()
    assert called == [role.id]
    admin_user.revoke_permission("volunteer:admin")
    db.session.commit()


def test_role_admin_required_allows_volunteer_manager_permission(admin_user, role, db):
    admin_user.grant_permission("volunteer:manager")
    db.session.commit()
    db.session.refresh(admin_user)
    called, mock_abort = _invoke(role.id, admin_user)
    mock_abort.assert_not_called()
    assert called == [role.id]
    admin_user.revoke_permission("volunteer:manager")
    db.session.commit()


def test_role_admin_required_unauthenticated(admin_user, db):
    db.session.refresh(admin_user)

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
