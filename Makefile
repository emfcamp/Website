ifeq ("$(TEST_SETTINGS)", "")
	TEST_SETTINGS=./config/test.cfg
endif

.PHONY: run update outdated listdepends clean

run:
	python ./dev_server.py

update:
	PIPENV_MAX_SUBPROCESS=$$(($$(nproc)+1)) pipenv sync --dev

deploy:
	PIPENV_MAX_SUBPROCESS=$$(($$(nproc)+1)) pipenv install --deploy

lock:
	pipenv lock

clean:
	rm -rf ./__pycache__  # In theory pycache should be version dependent
	rm -rf ./lib          # & this shouldn't exist any more
	rm -rf ./env


db:
	python ./utils.py db upgrade

migrate:
	python ./utils.py db migrate -m '$(msg)'

data: db perms tickets bankaccounts importvenues

dev-data: volunteerdata volunteershifts fakedata

exportdb:
	python ./utils.py exportdb

perms:
	python ./utils.py createperms

tickets:
	python ./utils.py createtickets

bankaccounts:
	python ./utils.py createbankaccounts

loadofx:
	python ./utils.py loadofx -f var/data.ofx
	python ./utils.py loadofx -f var/data-eur.ofx

checkreconcile:
	python ./utils.py reconcile

reallyreconcile:
	python ./utils.py reconcile -d

cancelreservedtickets:
	python ./utils.py cancelreservedtickets

pyppeteer:
	sudo -u www-data pipenv run ./pyppeteer-launcher.py

sendtickets:
	python ./utils.py sendtickets

fakedata:
	python ./utils.py makefakedata

volunteerdata:
	python ./utils.py makevolunteerdata

volunteershifts:
	python ./utils.py makevolunteershifts

shiftsfromproposals:
	python ./utils.py makeshiftsfromproposals

lockproposals:
	python ./utils.py lockproposals

importcfp:
	python ./utils.py importcfp

emailspeakersaboutslot:
	python ./utils.py emailspeakersaboutslot

emailspeakersaboutfinalising:
	python ./utils.py emailspeakersaboutfinalising

emailspeakersaboutreservelist:
	python ./utils.py emailspeakersaboutreservelist

importvenues:
	python ./utils.py importvenues

setroughdurations:
	python ./utils.py setroughdurations

runscheduler:
	python ./utils.py runscheduler -p

applypotentialschedule:
	python ./utils.py applypotentialschedule

shell:
	PYTHONPATH=. FLASK_APP=wsgi flask shell

sendemails:
	python ./utils.py sendemails

admin:
	python ./utils.py makeadmin ${ARGS}

arrivals:
	python ./utils.py makearrivals

calendars:
	python ./utils.py createcalendars

refreshcalendars:
	python ./utils.py refreshcalendars

exportcalendars:
	python ./utils.py exportcalendars

parkingtickets:
	python ./utils.py createparkingtickets

matchyoutube:
	python ./utils.py matchyoutube

test:
	black --check ./apps ./models ./tasks ./tests
	flake8 ./*.py ./models ./apps ./tasks ./utils.py
	SETTINGS_FILE=$(TEST_SETTINGS) pytest --random-order ./tests/ ./models/

testdb:
	SETTINGS_FILE=$(TEST_SETTINGS) python ./utils.py db upgrade

