#
# These are run via the './run_tests' script
#

ifeq ("$(TEST_SETTINGS)", "")
	TEST_SETTINGS=./config/test.cfg
endif

.PHONY: test check-syntax fix-syntax pytest

test: check-syntax pytest

pytest:
	SETTINGS_FILE=$(TEST_SETTINGS) pytest --random-order --cov=apps --cov=models ./tests/ ./models/
	SETTINGS_FILE=$(TEST_SETTINGS) flask db upgrade
	SETTINGS_FILE=$(TEST_SETTINGS) flask db check

check-syntax:
	uv lock --check
	ruff format --check ./*.py ./apps ./models ./tests
	ruff check ./*.py ./apps ./models ./tests
	mypy ./*.py ./apps ./models --txt-report mypy-report


fix-syntax:
	ruff format ./*.py ./apps ./models ./tests
	ruff check --fix ./*.py ./apps ./models ./tests
	mypy ./*.py ./apps ./models
