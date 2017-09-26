ifeq ("$(SETTINGS)", "")
	ifeq ("$(wildcard ./config/live.cfg)", "")
		SETTINGS=./config/development.cfg
	else
		SETTINGS=./config/live.cfg
	endif
endif

ifeq ("$(VIRTUAL_ENV)", "")
  ENV=. env/bin/activate;
endif

run:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./dev_server.py

init:
	virtualenv -p python3 --clear ./env

update:
	$(ENV) pip install --upgrade pip wheel setuptools
	$(ENV) pip install ndg-httpsclient
	$(ENV) pip install -r ./requirements.txt

outdated:
	$(ENV) pip list --outdated

listdepends:
	$(ENV) pip list|cut -d\  -f1|while read x; do echo $$x $$(pip show $$x|grep Requires); done

clean:
	rm -rf ./__pycache__  # In theory pycache should be version dependent
	rm -rf ./lib          # & this shouldn't exist any more
	rm -rf ./env


db:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py db upgrade

migrate:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py db migrate -m '$(msg)'

data: db perms tickets bankaccounts

perms:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py createperms

tickets:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py createtickets

bankaccounts:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py createbankaccounts

loadofx:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py loadofx -f var/data.ofx
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py loadofx -f var/data-eur.ofx

checkreconcile:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py reconcile

reallyreconcile:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py reconcile -d

sendtickets:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py sendtickets

faketickets:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py makefaketickets

lockproposals:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py lockproposals

importcfp:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py importcfp

emailspeakersaboutslot:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py emailspeakersaboutslot

emailspeakersaboutfinalising:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py emailspeakersaboutfinalising

rejectunacceptedtalks:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py rejectunacceptedtalks

importvenues:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py importvenues

setroughdurations:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py setroughdurations

outputschedulerdata:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py outputschedulerdata

importschedulerdata:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py importschedulerdata --persist

runscheduler:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py outputschedulerdata
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py runscheduler
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py importschedulerdata

applypotentialschedule:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py applypotentialschedule

shell:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py shell

testemails:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py testemails

admin:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py makeadmin

users:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py makefakeusers

arrivals:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py makearrivals

calendars:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py createcalendars

refreshcalendars:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py refreshcalendars

exportcalendars:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py exportcalendars

parkingtickets:
	$(ENV) SETTINGS_FILE=$(SETTINGS) python ./utils.py createparkingtickets

test:
	$(ENV) SETTINGS_FILE=./config/test.cfg flake8 ./*.py ./models ./apps ./utils.py
	$(ENV) SETTINGS_FILE=./config/test.cfg nosetests ./utils.py ./tests/ ./models/

