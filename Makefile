#
# These are run via the './run_tests' script
#

ifeq ("$(TEST_SETTINGS)", "")
	TEST_SETTINGS=./config/test.cfg
endif

.PHONY: test check-syntax fix-syntax

test:
	ruff check ./main.py ./apps ./models ./tests
	mypy ./*.py ./apps ./models
	SETTINGS_FILE=$(TEST_SETTINGS) pytest --random-order --cov=apps --cov=models ./tests/ ./models/
#ifdef COVERALLS_REPO_TOKEN
#	coveralls
#endif

check-syntax:
	ruff check ./main.py ./apps ./models ./tests
	mypy ./*.py ./apps ./models

fix-syntax:
	ruff check --fix ./main.py ./apps ./models ./tests
	mypy ./*.py ./apps ./models
