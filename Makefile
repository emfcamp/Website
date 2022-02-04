#
# These are run via the './run_tests' script
#

ifeq ("$(TEST_SETTINGS)", "")
	TEST_SETTINGS=./config/test.cfg
endif

.PHONY: test check-syntax

test:
	black --check ./main.py ./apps ./models ./tests
	flake8 ./*.py ./apps ./models ./tests
	mypy ./*.py ./apps ./models
	SETTINGS_FILE=$(TEST_SETTINGS) pytest --random-order --cov=apps --cov=models ./tests/ ./models/
ifdef COVERALLS_REPO_TOKEN
	coveralls
endif

check-syntax:
	black --check ./main.py ./apps ./models ./tests
	flake8 ./*.py ./apps ./models ./tests
	mypy ./*.py ./apps ./models

