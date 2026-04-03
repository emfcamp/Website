"""Tests for team admin functionality."""

from unittest.mock import MagicMock, patch

import pytest

from apps.volunteer.team_admin import team_admin_required
from models.volunteer.role import Team


@pytest.fixture()
def team(db):
    t = Team(name="Test Team", slug="test-team")
    db.session.add(t)
    return t


def _invoke(team_id, volunteer):
    """Call a role_admin_required-decorated view, return (was_called, abort_mock)."""
    called = []

    @team_admin_required
    def view(team_id):
        called.append(team_id)
        return "ok"

    mock_app = MagicMock()
    with (
        patch("apps.volunteer.team_admin.current_user", volunteer.user),
        patch("apps.volunteer.team_admin.abort") as mock_abort,
        patch("apps.volunteer.team_admin.app", mock_app),
    ):
        view(team_id)

    return called, mock_abort


def test_team_admin_required_denies_non_admin(volunteer, db):
    db.session.refresh(volunteer)
    called, mock_abort = _invoke(42, volunteer)
    mock_abort.assert_called_once_with(404)
    assert called == []


def test_team_admin_required_allows_assigned_team_admin(volunteer, team, db):
    team.admins.append(volunteer)
    db.session.add(team)
    db.session.flush()
    called, mock_abort = _invoke(team.id, volunteer)
    mock_abort.assert_not_called()
    assert called == [team.id]


def test_team_admin_required_allows_volunteer_admin_permission(volunteer, team, db):
    volunteer.user.grant_permission("volunteer:admin")
    db.session.flush()
    called, mock_abort = _invoke(team.id, volunteer)
    mock_abort.assert_not_called()
    assert called == [team.id]


def test_team_admin_required_disallows_volunteer_manager_permission(volunteer, team, db):
    volunteer.user.grant_permission("volunteer:manager")
    db.session.flush()
    called, mock_abort = _invoke(team.id, volunteer)
    mock_abort.assert_called_once_with(404)
    assert called == []


def test_team_admin_required_unauthenticated(volunteer, db):
    @team_admin_required
    def view(team_id):
        return "ok"

    mock_app = MagicMock()
    mock_user = MagicMock(is_authenticated=False)
    with (
        patch("apps.volunteer.team_admin.current_user", mock_user),
        patch("apps.volunteer.team_admin.app", mock_app),
    ):
        view(42)
        mock_app.login_manager.unauthorized.assert_called_once()
