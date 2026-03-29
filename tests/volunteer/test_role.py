"""Tests for Role.from_dict."""

import pytest

from models.volunteer.role import Role, Team


@pytest.fixture(scope="module")
def team(db):
    t = Team(name="Role Test Team", slug="role-test-team")
    db.session.add(t)
    return t


def test_from_dict_creates_new_role(db, team):
    data = {
        "name": "Brand New Role",
        "description": "A new role",
        "full_description_md": "## Details",
        "role_notes": "Some notes",
        "over_18_only": True,
        "requires_training": True,
    }
    role = Role.from_dict(data)
    role.team = team
    db.session.add(role)

    assert role.name == "Brand New Role"
    assert role.description == "A new role"
    assert role.full_description_md == "## Details"
    assert role.role_notes == "Some notes"
    assert role.over_18_only is True
    assert role.requires_training is True


def test_from_dict_updates_existing_role(db, team):
    existing = Role(name="Existing Role", description="Old description", team=team)
    db.session.add(existing)

    data = {
        "name": "Existing Role",
        "description": "Updated description",
        "full_description_md": "## Updated",
        "role_notes": "Updated notes",
        "over_18_only": True,
        "requires_training": True,
    }
    role = Role.from_dict(data)

    assert role is existing
    assert role.description == "Updated description"
    assert role.full_description_md == "## Updated"
    assert role.role_notes == "Updated notes"
    assert role.over_18_only is True
    assert role.requires_training is True


def test_from_dict_optional_fields_default(db, team):
    data = {"name": "Minimal Role", "description": "Minimal"}
    role = Role.from_dict(data)

    assert role.full_description_md == ""
    assert role.role_notes is None
    assert role.over_18_only is False
    assert role.requires_training is False
