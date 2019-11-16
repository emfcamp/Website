ifeq ("$(TEST_SETTINGS)", "")
	TEST_SETTINGS=./config/test.cfg
endif

.PHONY: test

test:
	black --check ./main.py ./apps ./models ./tests
	flake8 ./*.py ./models ./apps
	SETTINGS_FILE=$(TEST_SETTINGS) pytest --random-order --cov=apps --cov=models ./tests/ ./models/
ifdef COVERALLS_REPO_TOKEN
	coveralls
endif
