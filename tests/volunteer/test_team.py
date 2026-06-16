"""Tests for Team model methods."""

from models.volunteer.role import Team


def test_from_dict_creates_new_team(db):
    data = {"slug": "brand-new-team", "name": "Brand New Team"}
    team = Team.from_dict(data)
    db.session.add(team)
    db.session.flush()

    assert team.slug == "brand-new-team"
    assert team.name == "Brand New Team"
    assert team.id is not None


def test_from_dict_updates_existing_team(db):
    existing = Team(slug="existing-team", name="Old Name")
    db.session.add(existing)
    db.session.flush()

    data = {"slug": "existing-team", "name": "Updated Name"}
    team = Team.from_dict(data)

    assert team is existing
    assert team.name == "Updated Name"
