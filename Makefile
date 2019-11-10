ifeq ("$(TEST_SETTINGS)", "")
	TEST_SETTINGS=./config/test.cfg
endif

.PHONY: test

test:
	black --check ./apps ./models ./tests
	flake8 ./*.py ./models ./apps
	SETTINGS_FILE=$(TEST_SETTINGS) pytest --random-order ./tests/ ./models/
