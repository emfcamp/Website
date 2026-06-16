from apps.volunteer.init_data import load_from_yaml


def test_load_from_yaml_adds_slug(app, tmp_path, monkeypatch):
    yaml_file = tmp_path / "my-slug.yml"
    yaml_file.write_text("name: Test Role\ndescription: A test\n")

    monkeypatch.setattr(app, "root_path", str(tmp_path))

    result = load_from_yaml("*.yml")

    assert len(result) == 1
    assert result[0]["slug"] == "my-slug"
    assert result[0]["name"] == "Test Role"


def test_load_from_yaml_converts_underscores_to_hyphens(app, tmp_path, monkeypatch):
    yaml_file = tmp_path / "some_role_name.yml"
    yaml_file.write_text("name: Some Role Name\n")

    monkeypatch.setattr(app, "root_path", str(tmp_path))

    result = load_from_yaml("*.yml")

    assert len(result) == 1
    assert result[0]["slug"] == "some-role-name"
