"""Tests for apps.common.archive_file: `year` must be a plain run of digits (#1779)."""

from pathlib import Path

import pytest
from werkzeug.exceptions import NotFound

from apps.common import archive_file

EXPORTS = (Path(__file__).resolve().parent.parent / "exports").resolve()
SCHEDULE_2024 = EXPORTS / "2024" / "public" / "schedule.json"


def test_int_year_returns_the_file():
    assert archive_file(2024, "public", "schedule.json") == SCHEDULE_2024


def test_digit_string_year_returns_the_file():
    assert archive_file("2024", "public", "schedule.json") == SCHEDULE_2024  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "year",
    ["2022/../2024", "../exports/2024", "/2024", "2024/", "2024/public", "20 24", "2024.0", "", True],
)
def test_year_that_is_not_digits_is_treated_as_missing(year):
    assert archive_file(year, "public", "schedule.json", raise_404=False) is None
    with pytest.raises(NotFound):
        archive_file(year, "public", "schedule.json")


def test_year_without_an_archive_is_missing():
    assert archive_file(1999, "public", "schedule.json", raise_404=False) is None
    with pytest.raises(NotFound):
        archive_file(1999, "public", "schedule.json")


def test_path_escaping_exports_is_still_blocked():
    assert archive_file(2024, "..", "..", "README.md", raise_404=False) is None
