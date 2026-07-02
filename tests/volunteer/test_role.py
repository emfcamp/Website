"""Tests for Role.from_dict."""

from datetime import datetime

import pytest

from models.volunteer.role import Role, Team
from models.volunteer.shift import Shift
from models.volunteer.venue import VolunteerVenue


@pytest.fixture(scope="module")
def team(db):
    t = Team(name="Role Test Team", slug="role-test-team")
    db.session.add(t)
    return t


def test_from_dict_creates_new_role(db, team):
    data = {
        "slug": "new-role",
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

    assert role.slug == "new-role"
    assert role.name == "Brand New Role"
    assert role.description == "A new role"
    assert role.full_description_md == "## Details"
    assert role.role_notes == "Some notes"
    assert role.over_18_only is True
    assert role.requires_training is True


def test_from_dict_updates_existing_role(db, team):
    existing = Role(slug="existing-role", name="Existing Role", description="Old description", team=team)
    db.session.add(existing)

    data = {
        "slug": "existing-role",
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
    data = {"slug": "minimal", "name": "Minimal Role", "description": "Minimal"}
    role = Role.from_dict(data)

    assert role.full_description_md == ""
    assert role.role_notes is None
    assert role.over_18_only is False
    assert role.requires_training is False


def test_grouped_by_team(db, team):
    venue = VolunteerVenue(slug="venue", name="Venue")

    role_with_shifts = Role(slug="role-with-shifts", name="Role With Shifts", description="", team=team)
    role_without_shifts = Role(
        slug="role-without-shifts", name="Role Without Shifts", description="", team=team
    )
    for _ in range(2):
        db.session.add(
            Shift(
                role=role_with_shifts,
                venue=venue,
                start=datetime(2026, 7, 17, 14, 30),
                end=datetime(2026, 7, 17, 16, 30),
            )
        )
    db.session.add(role_without_shifts)
    db.session.flush()

    grouped = Role.grouped_by_team(only=[role_with_shifts.id, role_without_shifts.id])

    assert [t.slug for t in grouped] == [team.slug]
    assert [r.slug for (r, _) in grouped[team]] == ["role-with-shifts", "role-without-shifts"]
    assert [count for (_, count) in grouped[team]] == [2, 0]
