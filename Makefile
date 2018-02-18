ifeq ("$(SETTINGS)", "")
	ifeq ("$(wildcard ./config/live.cfg)", "")
		SETTINGS=./config/development.cfg
	else
		SETTINGS=./config/live.cfg
	endif
endif

ifeq ("$(TEST_SETTINGS)", "")
	TEST_SETTINGS=./config/test.cfg
endif

.PHONY: run update outdated listdepends clean

run:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./dev_server.py

update:
	PIPENV_MAX_SUBPROCESS=$$(($$(nproc)+1)) pipenv install --dev --ignore-pipfile

lock:
	PIPENV_MAX_SUBPROCESS=$$(($$(nproc)+1)) pipenv install --dev
	pipenv lock

clean:
	rm -rf ./__pycache__  # In theory pycache should be version dependent
	rm -rf ./lib          # & this shouldn't exist any more
	rm -rf ./env


db:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py db upgrade

migrate:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py db migrate -m '$(msg)'

data: db perms tickets bankaccounts

exportdb:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py exportdb

perms:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py createperms

tickets:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py createtickets

bankaccounts:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py createbankaccounts

loadofx:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py loadofx -f var/data.ofx
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py loadofx -f var/data-eur.ofx

checkreconcile:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py reconcile

reallyreconcile:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py reconcile -d

sendtickets:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py sendtickets

faketickets:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py makefaketickets

lockproposals:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py lockproposals

importcfp:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py importcfp

emailspeakersaboutslot:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py emailspeakersaboutslot

emailspeakersaboutfinalising:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py emailspeakersaboutfinalising

rejectunacceptedtalks:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py rejectunacceptedtalks

importvenues:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py importvenues

setroughdurations:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py setroughdurations

outputschedulerdata:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py outputschedulerdata

importschedulerdata:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py importschedulerdata --persist

runscheduler:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py outputschedulerdata
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py runscheduler
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py importschedulerdata

applypotentialschedule:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py applypotentialschedule

shell:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py shell

testemails:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py testemails

admin:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py makeadmin ${ARGS}

users:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py makefakeusers

arrivals:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py makearrivals

calendars:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py createcalendars

refreshcalendars:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py refreshcalendars

exportcalendars:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py exportcalendars

parkingtickets:
	SETTINGS_FILE=$(SETTINGS) pipenv run python ./utils.py createparkingtickets

test:
	SETTINGS_FILE=$(TEST_SETTINGS) pipenv run flake8 ./*.py ./models ./apps ./tasks ./utils.py
	SETTINGS_FILE=$(TEST_SETTINGS) pipenv run pytest ./tests/ ./models/

testdb:
	SETTINGS_FILE=$(TEST_SETTINGS) pipenv run python ./utils.py db upgrade

